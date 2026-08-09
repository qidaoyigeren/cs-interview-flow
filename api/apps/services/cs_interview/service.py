"""Transactional application service for CS interview sessions."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from api.apps.services.cs_interview.domain import (
    DomainError,
    PlannerAction,
    PlannerActionKind,
    RoundStatus,
    SessionStatus,
    build_report,
    choose_after_answer_action_versioned,
    choose_planner_action_versioned,
    compute_next_difficulty,
    merge_candidate_state,
    payload_hash,
    update_interview_plan,
    utcnow,
    validate_answer,
    validate_code_request,
)
from api.apps.services.cs_interview.observability import (
    RUNNER_EXECUTION,
    RUNNER_TIMEOUT,
    SESSION_COMPLETION,
    SESSION_FAILURE,
    metric_attributes,
)
from api.apps.services.cs_interview.pipeline import (
    RAGFlowRuntimeAdapter,
    RuntimeAdapter,
    extract_answer_state,
    generate_followup,
    generate_question,
    judge_answer,
)
from api.apps.services.cs_interview.reliability import classify_failure
from api.apps.services.cs_interview.runner import CodeRunner, IsolatedCodeRunner
from api.apps.services.cs_interview.slo import record_stage_latency
from api.apps.services.cs_interview.tracing import TRACE_EMITTER, TraceEventKind
from api.db.db_models import DB, CodeSubmission, InterviewReport, InterviewRound, InterviewSession
from api.db.services.interview_operation_service import operation_is_cancelled
from api.db.services.interview_service import (
    InterviewRequestService,
    InterviewSessionRepository,
    _timestamps,
    _touch,
    complete_code_submission,
    create_code_submission,
    public_code_submission,
    public_report,
    public_round,
    public_session,
)
from common.misc_utils import get_uuid

LOGGER = logging.getLogger(__name__)

PIPELINE_FAILURE_CODES = {
    "retrieval_failed",
    "insufficient_evidence",
    "no_eligible_topic",
    "invalid_question",
    "invalid_judge_output",
    "invalid_followup",
    "followup_leakage",
    "invalid_answer_state",
    "ungrounded_question",
    "question_answer_leakage",
    "jd_irrelevant_question",
    "code_question_preflight_failed",
}


class InterviewApplication:
    def __init__(self, runtime: RuntimeAdapter | None = None, runner: CodeRunner | None = None):
        self.runtime = runtime or RAGFlowRuntimeAdapter()
        self.runner = runner or IsolatedCodeRunner()

    def create_session(
        self,
        tenant_id: str,
        user_id: str,
        profile_id: str,
        knowledge_config_id: str,
    ) -> dict[str, Any]:
        with DB.atomic():
            session = InterviewSessionRepository.create(
                tenant_id,
                user_id,
                profile_id,
                knowledge_config_id,
            )
        TRACE_EMITTER.emit(
            TraceEventKind.SESSION_CREATED.value,
            session_id=session.id,
            tenant_id=tenant_id,
            metadata={"status": session.status},
            immediate=True,
        )
        return public_session(session)

    def _question_inputs(self, session: InterviewSession) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        from api.apps.services.cs_interview.ops_service import blocked_resource_ids

        history = [dict(row.__data__) for row in InterviewSessionRepository.rounds(session.id) if row.status == RoundStatus.COMPLETED.value]
        config = {
            **dict(session.knowledge_config_snapshot or {}),
            "blocked_evidence_ids": sorted(blocked_resource_ids(session.tenant_id, "evidence")),
            "blocked_question_ids": sorted(blocked_resource_ids(session.tenant_id, "question")),
        }
        return dict(session.profile_snapshot or {}), config, history

    async def _preflight_question(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Run every generated coding question before it can reach a candidate."""

        if snapshot.get("question_type") != "coding" and snapshot.get("category") != "leetcode":
            return snapshot
        rubric = snapshot.get("evaluation_rubric") if isinstance(snapshot.get("evaluation_rubric"), dict) else {}
        code_spec = rubric.get("code_spec") if isinstance(rubric, dict) else None
        if not isinstance(code_spec, dict):
            raise DomainError("code_question_preflight_failed", "A coding question requires a validated code specification.")
        visible = code_spec.get("visible_tests")
        hidden = code_spec.get("hidden_tests")
        if not isinstance(visible, list) or not visible or not isinstance(hidden, list) or not hidden:
            raise DomainError("code_question_preflight_failed", "Coding questions require both visible and hidden tests.")
        language, reference_solution, tests = validate_code_request(
            code_spec.get("language"),
            code_spec.get("reference_solution"),
            [*visible, *hidden],
        )
        try:
            result = await self.runner.execute(language, reference_solution, tests)
        except DomainError as exc:
            raise DomainError("code_question_preflight_failed", "The coding question could not be validated by the isolated runner.", http_status=409) from exc
        if result.get("status") != "completed" or int(result.get("passed_count") or 0) != len(tests) or int(result.get("total_count") or 0) != len(tests):
            raise DomainError("code_question_preflight_failed", "The reference solution did not pass every visible and hidden test.", http_status=409)
        snapshot["question_validation"] = {
            **(snapshot.get("question_validation") or {}),
            "code_preflight": {
                "status": "passed",
                "language": language,
                "visible_test_count": len(visible),
                "hidden_test_count": len(hidden),
            },
        }
        return snapshot

    async def _generate_question_for_action(self, session: InterviewSession, action) -> dict[str, Any]:
        profile, config, history = self._question_inputs(session)
        started = time.monotonic()
        snapshot = await generate_question(
            self.runtime,
            session.tenant_id,
            profile,
            config,
            history,
            action,
            resume_context=session.resume_snapshot or None,
            job_context=session.job_snapshot or None,
        )
        record_stage_latency("question_preparation", int((time.monotonic() - started) * 1000))
        return await self._preflight_question(snapshot)

    def _fail_session(self, session_id: str, tenant_id: str, user_id: str, code: str) -> None:
        with DB.atomic():
            session = InterviewSession.get_or_none((InterviewSession.id == session_id) & (InterviewSession.tenant_id == tenant_id) & (InterviewSession.user_id == user_id))
            if session is None or session.status not in {
                SessionStatus.PREPARING_QUESTION.value,
                SessionStatus.EVALUATING.value,
            }:
                return
            active = InterviewSessionRepository.active_round(session.id)
            if active and active.status != RoundStatus.FAILED.value:
                InterviewRound.update(status=RoundStatus.FAILED.value, active_guard=None, **_touch()).where(InterviewRound.id == active.id).execute()
            InterviewSessionRepository.transition(session, SessionStatus.FAILED.value, failure_code=code)
            SESSION_FAILURE.add(1, metric_attributes(error_code=code, status="failed"))
            TRACE_EMITTER.emit(
                TraceEventKind.SESSION_FAILED.value,
                session_id=session.id,
                tenant_id=session.tenant_id,
                status="failed",
                error_code=code,
            )

    @staticmethod
    def _ensure_operation_active(operation_id: str | None) -> None:
        if operation_id and operation_is_cancelled(operation_id):
            raise DomainError("operation_cancelled", "The interview operation was cancelled.", http_status=409)

    async def start_events(
        self,
        session_id: str,
        tenant_id: str,
        user_id: str,
        request_id: str,
        expected_version: int,
        operation_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        request_row = None
        replay_events = None
        digest = payload_hash({"expected_version": expected_version})
        try:
            with DB.atomic():
                session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
                request_row, replay = InterviewRequestService.begin(session.id, request_id, "start", digest, operation_id=operation_id)
                if replay:
                    replay_events = list(request_row.response.get("events", []))
                elif session.status == SessionStatus.CREATED.value:
                    session = InterviewSessionRepository.transition(
                        session,
                        SessionStatus.PREPARING_QUESTION.value,
                        expected_version=expected_version,
                        started_at=utcnow(),
                        model_config_snapshot={
                            **self.runtime.model_snapshot(tenant_id),
                            **dict(session.model_config_snapshot or {}),
                        },
                        prompt_version=session.prompt_version,
                    )
                elif not operation_id or session.status != SessionStatus.PREPARING_QUESTION.value:
                    raise DomainError("state_conflict", "The session cannot resume question preparation.", http_status=409)

            if replay_events is not None:
                for event in replay_events:
                    yield event
                return

            history = [dict(row.__data__) for row in InterviewSessionRepository.rounds(session.id)]
            action = choose_planner_action_versioned(
                session.planner_version,
                list(session.current_interview_plan or []),
                dict(session.current_candidate_state or {}),
                history,
                remaining_question_budget=session.max_questions - session.completed_question_count,
                current_difficulty=session.current_difficulty,
            )
            if action.selected_action == PlannerActionKind.FINISH_INTERVIEW.value:
                raise DomainError("no_eligible_topic", "The interview plan has no grounded topic to ask.", http_status=409)
            TRACE_EMITTER.emit(
                TraceEventKind.PLANNER_ACTION_SELECTED.value,
                session_id=session.id,
                tenant_id=session.tenant_id,
                round_id=None,
                planner_version=action.planner_version,
                prompt_version=session.prompt_version,
                metadata={
                    "selected_action": action.selected_action,
                    "target_requirement_id": action.target_requirement_id,
                    "target_topic": action.target_topic,
                    "reason_branch": (action.decision_audit or {}).get("reason_branch", "planner"),
                },
            )
            snapshot = await self._generate_question_for_action(session, action)
            self._ensure_operation_active(operation_id)
            with DB.atomic():
                session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
                if session.status != SessionStatus.PREPARING_QUESTION.value:
                    raise DomainError("state_conflict", "The session changed while preparing the question.", http_status=409)
                round_ = InterviewSessionRepository.create_round(session, snapshot)
                round_ = InterviewSessionRepository.transition_round(round_, RoundStatus.AWAITING_ANSWER.value)
                session = InterviewSessionRepository.transition(
                    session,
                    SessionStatus.AWAITING_ANSWER.value,
                    current_round_sequence=round_.sequence,
                )
                event = {
                    "event": "next_question",
                    "data": {"session": public_session(session), "round": public_round(round_, include_evaluation=False)},
                }
                InterviewRequestService.finish(request_row, {"events": [event]})
            yield event
        except DomainError as error:
            if operation_id and classify_failure(error).retryable:
                raise
            if request_row is not None:
                InterviewRequestService.fail(request_row, error)
            if error.code in PIPELINE_FAILURE_CODES:
                self._fail_session(session_id, tenant_id, user_id, error.code)
            raise
        except Exception as exc:
            LOGGER.exception("CS interview start failed", extra={"session_id": session_id})
            error = DomainError("question_generation_failed", "The first grounded question could not be prepared.", http_status=500)
            if operation_id:
                raise error from exc
            if request_row is not None:
                InterviewRequestService.fail(request_row, error)
            self._fail_session(session_id, tenant_id, user_id, error.code)
            raise error from exc

    async def answer_events(
        self,
        session_id: str,
        tenant_id: str,
        user_id: str,
        answer: str,
        request_id: str,
        expected_version: int,
        operation_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        answer = validate_answer(answer)
        digest = payload_hash({"answer": answer, "expected_version": expected_version})
        request_row = None
        replay_events = None
        events: list[dict[str, Any]] = []
        try:
            with DB.atomic():
                session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
                request_row, replay = InterviewRequestService.begin(session.id, request_id, "answer", digest, operation_id=operation_id)
                if replay:
                    replay_events = list(request_row.response.get("events", []))
                elif operation_id and session.status == SessionStatus.EVALUATING.value:
                    round_ = InterviewSessionRepository.active_round(session.id)
                    if round_ is None or round_.status != RoundStatus.EVALUATING.value:
                        raise DomainError("state_conflict", "The evaluating round cannot be recovered.", http_status=409)
                    answers = list(round_.candidate_answers or [])
                    if not answers or answers[-1].get("answer") != answer:
                        raise DomainError("state_conflict", "The persisted answer differs from the operation payload.", http_status=409)
                elif operation_id and session.status == SessionStatus.PREPARING_QUESTION.value:
                    round_ = None
                else:
                    if session.status in {SessionStatus.COMPLETED.value, SessionStatus.ABORTED.value}:
                        raise DomainError("session_terminal", "A completed or aborted interview cannot accept answers.", http_status=409)
                    if session.status != SessionStatus.AWAITING_ANSWER.value:
                        raise DomainError("not_awaiting_answer", "The interview is not waiting for an answer.", http_status=409)
                    round_ = InterviewSessionRepository.active_round(session.id)
                    if round_ is None or round_.status not in {
                        RoundStatus.AWAITING_ANSWER.value,
                        RoundStatus.AWAITING_FOLLOWUP.value,
                    }:
                        raise DomainError("active_round_missing", "No answerable interview round exists.", http_status=409)
                    running_code = CodeSubmission.select().where((CodeSubmission.round_id == round_.id) & (CodeSubmission.execution_status.in_(("queued", "running"))))
                    if running_code.exists():
                        raise DomainError(
                            "code_execution_in_progress",
                            "Wait for the active code execution before submitting the answer.",
                            http_status=409,
                        )
                    session = InterviewSessionRepository.transition(
                        session,
                        SessionStatus.EVALUATING.value,
                        expected_version=expected_version,
                    )
                    answer_kind = "followup" if round_.status == RoundStatus.AWAITING_FOLLOWUP.value else "initial"
                    answers = list(round_.candidate_answers or [])
                    answers.append({"kind": answer_kind, "answer": answer, "submitted_at": utcnow().isoformat()})
                    round_ = InterviewSessionRepository.transition_round(
                        round_,
                        RoundStatus.EVALUATING.value,
                        candidate_answers=answers,
                        answered_at=utcnow(),
                    )

            if replay_events is not None:
                for event in replay_events:
                    yield event
                return

            if operation_id and session.status == SessionStatus.PREPARING_QUESTION.value and round_ is None:
                async for event in self._resume_next_question(
                    session,
                    tenant_id,
                    user_id,
                    request_row,
                    operation_id,
                ):
                    yield event
                return

            received_event = {
                "event": "answer_received",
                "data": {"session_id": session.id, "round_id": round_.id, "state_version": session.state_version},
            }
            evaluating_event = {"event": "evaluating", "data": {"session_id": session.id, "round_id": round_.id}}
            events.extend([received_event, evaluating_event])
            TRACE_EMITTER.emit(
                TraceEventKind.ANSWER_RECEIVED.value,
                session_id=session.id,
                tenant_id=session.tenant_id,
                round_id=round_.id,
                metadata={"round_sequence": round_.sequence, "answer_kind": answer_kind},
            )
            yield received_event
            yield evaluating_event

            history = [dict(row.__data__) for row in InterviewSessionRepository.rounds(session.id) if row.status == RoundStatus.COMPLETED.value]
            code_result = None
            if round_.code_submission_id:
                submission = CodeSubmission.get_or_none(CodeSubmission.id == round_.code_submission_id)
                if submission:
                    code_result = {
                        "status": submission.execution_status,
                        "passed_count": submission.passed_count,
                        "total_count": submission.total_count,
                        "runtime_ms": submission.runtime_ms,
                    }
            judge_started = time.monotonic()
            judge_task = judge_answer(
                self.runtime,
                tenant_id,
                dict(round_.__data__),
                history,
                session.max_followups,
                code_result,
            )
            state_task = extract_answer_state(
                self.runtime,
                tenant_id,
                answer,
                resume_snapshot=session.resume_snapshot or None,
                candidate_state=session.current_candidate_state or None,
                round_data=dict(round_.__data__),
            )
            result, answer_state = await asyncio.gather(judge_task, state_task)
            judge_duration_ms = int((time.monotonic() - judge_started) * 1000)
            record_stage_latency("judge", judge_duration_ms)
            TRACE_EMITTER.emit(
                TraceEventKind.JUDGE_COMPLETED.value,
                session_id=session.id,
                tenant_id=session.tenant_id,
                round_id=round_.id,
                duration_ms=judge_duration_ms,
                metadata={
                    "score": result.score,
                    "verdict": result.verdict,
                    "judge_confidence": result.confidence,
                    "needs_followup": result.needs_followup,
                    "reason": "judge_completed",
                },
            )
            TRACE_EMITTER.emit(
                TraceEventKind.ANSWER_STATE_EXTRACTED.value,
                session_id=session.id,
                tenant_id=session.tenant_id,
                round_id=round_.id,
                metadata={
                    "new_claim_count": len(answer_state.get("newly_claimed_facts") or []),
                    "contradiction_count": len(answer_state.get("contradictions") or []),
                    "project_fact_count": len(answer_state.get("project_facts") or []),
                },
            )
            self._ensure_operation_active(operation_id)
            previous_score = history[-1].get("score") if history else None
            next_difficulty = compute_next_difficulty(session.current_difficulty, result.score, previous_score)
            requirement_id = round_.target_requirement_id or None
            targeted_claim_facts: list[str] = []
            resolved_contradiction_ids: list[str] = []
            if round_.planner_actions:
                answered_action = round_.planner_actions[-1]
                if answered_action.get("selected_action") == PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value:
                    target_claim = str((answered_action.get("supporting_state") or {}).get("target_claim_fact") or "").strip()
                    if target_claim:
                        targeted_claim_facts.append(target_claim)
                elif answered_action.get("selected_action") == PlannerActionKind.RESOLVE_CONTRADICTION.value and result.score >= 2:
                    # Only the contradiction that was explicitly pursued by the
                    # follow-up may be resolved.  Same-topic siblings stay
                    # unresolved so they can be clarified separately.
                    cid = str((answered_action.get("supporting_state") or {}).get("target_contradiction_id") or "").strip()
                    if cid:
                        resolved_contradiction_ids.append(cid)
            provisional_state = merge_candidate_state(
                dict(session.current_candidate_state or {}),
                answer_state,
                result,
                requirement_id=requirement_id,
                target_topic=round_.topic,
                completed=True,
                targeted_claim_facts=targeted_claim_facts,
                resolved_contradiction_ids=resolved_contradiction_ids,
            )
            provisional_plan = update_interview_plan(
                list(session.current_interview_plan or []),
                requirement_id,
                score=result.score,
                completed=True,
            )
            completed_count = session.completed_question_count + 1
            action = choose_after_answer_action_versioned(
                session.planner_version,
                provisional_plan,
                provisional_state,
                answer_state,
                result,
                dict(round_.__data__),
                [*history, dict(round_.__data__)],
                remaining_question_budget=session.max_questions - completed_count,
                max_followups=session.max_followups,
                current_difficulty=next_difficulty,
            )
            followup_action = (
                action.selected_action
                in {
                    PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value,
                    PlannerActionKind.RESOLVE_CONTRADICTION.value,
                }
                and action.target_topic == round_.topic
            )

            if followup_action:
                TRACE_EMITTER.emit(
                    TraceEventKind.FOLLOWUP_SELECTED.value,
                    session_id=session.id,
                    tenant_id=session.tenant_id,
                    round_id=round_.id,
                    metadata={
                        "selected_action": action.selected_action,
                        "target_requirement_id": action.target_requirement_id,
                        "target_topic": action.target_topic,
                        "target_contradiction_id": action.target_contradiction_id,
                        "reason_branch": (action.decision_audit or {}).get("reason_branch", ""),
                    },
                )
                state = merge_candidate_state(
                    dict(session.current_candidate_state or {}),
                    answer_state,
                    result,
                    requirement_id=requirement_id,
                    target_topic=round_.topic,
                    completed=False,
                    resolved_contradiction_ids=resolved_contradiction_ids,
                )
                state["next_action_reason"] = action.reason
                plan = update_interview_plan(
                    list(session.current_interview_plan or []),
                    requirement_id,
                    score=None,
                    completed=False,
                )
                followup = await generate_followup(self.runtime, tenant_id, dict(round_.__data__), action)
                self._ensure_operation_active(operation_id)
                with DB.atomic():
                    session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
                    round_ = InterviewSessionRepository.active_round(session.id)
                    if session.status != SessionStatus.EVALUATING.value or round_ is None or round_.status != RoundStatus.EVALUATING.value:
                        raise DomainError("state_conflict", "The session changed during evaluation.", http_status=409)
                    answers = list(round_.candidate_answers or [])
                    answers[-1] = {**answers[-1], "evaluation": asdict(result)}
                    followups = list(round_.followup_questions or [])
                    followups.append(
                        {
                            "sequence": round_.followup_count + 1,
                            "question": followup,
                            "selected_action": action.selected_action,
                            "reason": action.reason,
                            "asked_at": utcnow().isoformat(),
                        }
                    )
                    state_log = dict(round_.answer_state or {})
                    state_log["extractions"] = [
                        *(state_log.get("extractions") or []),
                        {"answer_sequence": len(answers), "state": answer_state},
                    ]
                    round_ = InterviewSessionRepository.transition_round(
                        round_,
                        RoundStatus.AWAITING_FOLLOWUP.value,
                        candidate_answers=answers,
                        followup_questions=followups,
                        followup_count=round_.followup_count + 1,
                        initial_score=round_.initial_score if round_.initial_score is not None else result.score,
                        judge_confidence=result.confidence,
                        answer_state=state_log,
                        planner_actions=[*(round_.planner_actions or []), asdict(action)],
                    )
                    session = InterviewSessionRepository.transition(
                        session,
                        SessionStatus.AWAITING_ANSWER.value,
                        current_candidate_state=state,
                        current_interview_plan=plan,
                    )
                    feedback_event = {
                        "event": "feedback",
                        "data": {"round_id": round_.id, "verdict": "partial", "feedback": result.feedback, "final": False},
                    }
                    followup_event = {
                        "event": "followup_question",
                        "data": {
                            "session_id": session.id,
                            "round_id": round_.id,
                            "question": followup,
                            "selected_action": action.selected_action,
                            "reason": action.reason,
                            "followup_count": round_.followup_count,
                            "max_followups": session.max_followups,
                            "state_version": session.state_version,
                        },
                    }
                    events.extend([feedback_event, followup_event])
                    InterviewRequestService.finish(request_row, {"events": events})
                yield feedback_event
                yield followup_event
                return

            provisional_state["next_action_reason"] = action.reason
            with DB.atomic():
                session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
                round_ = InterviewSessionRepository.active_round(session.id)
                if session.status != SessionStatus.EVALUATING.value or round_ is None or round_.status != RoundStatus.EVALUATING.value:
                    raise DomainError("state_conflict", "The session changed during evaluation.", http_status=409)
                answers = list(round_.candidate_answers or [])
                answers[-1] = {**answers[-1], "evaluation": asdict(result)}
                state_log = dict(round_.answer_state or {})
                state_log["extractions"] = [
                    *(state_log.get("extractions") or []),
                    {"answer_sequence": len(answers), "state": answer_state},
                ]
                round_ = InterviewSessionRepository.transition_round(
                    round_,
                    RoundStatus.COMPLETED.value,
                    candidate_answers=answers,
                    initial_score=round_.initial_score if round_.initial_score is not None else result.score,
                    score=result.score,
                    verdict=result.verdict,
                    judge_confidence=result.confidence,
                    weak_point=result.weak_point,
                    feedback=result.feedback,
                    next_difficulty=next_difficulty,
                    evaluation_summary=result.evaluation_summary,
                    completed_at=utcnow(),
                    answer_state=state_log,
                    planner_actions=[*(round_.planner_actions or []), asdict(action)],
                )
                feedback_event = {
                    "event": "feedback",
                    "data": {
                        "round_id": round_.id,
                        "score": result.score,
                        "verdict": result.verdict,
                        "weak_point": result.weak_point,
                        "feedback": result.feedback,
                        "evaluation_summary": result.evaluation_summary,
                        "final": True,
                        "next_difficulty": next_difficulty,
                        "next_action": action.selected_action,
                        "next_action_reason": action.reason,
                    },
                }
                events.append(feedback_event)

                should_finish = completed_count >= session.max_questions or action.selected_action == PlannerActionKind.FINISH_INTERVIEW.value
                if should_finish:
                    report_data = build_report(
                        [dict(row.__data__) for row in InterviewSessionRepository.rounds(session.id)],
                        dict(session.profile_snapshot or {}),
                        resume_snapshot=session.resume_snapshot or None,
                        job_snapshot=session.job_snapshot or None,
                        match_snapshot=list(session.match_snapshot or []),
                    )
                    report = InterviewReport.create(id=get_uuid(), session_id=session.id, **report_data, **_timestamps())
                    session = InterviewSessionRepository.transition(
                        session,
                        SessionStatus.COMPLETED.value,
                        completed_question_count=completed_count,
                        current_difficulty=next_difficulty,
                        current_candidate_state=provisional_state,
                        current_interview_plan=provisional_plan,
                        performance_snapshot=report_data["metrics"],
                        completed_at=utcnow(),
                    )
                    SESSION_COMPLETION.add(1, metric_attributes(status="completed"))
                    TRACE_EMITTER.emit(
                        TraceEventKind.REPORT_GENERATED.value,
                        session_id=session.id,
                        tenant_id=session.tenant_id,
                        round_id=round_.id,
                        metadata={"report_version": report.report_version or "", "overall_score": report_data.get("overall_score")},
                    )
                    TRACE_EMITTER.emit(
                        TraceEventKind.SESSION_COMPLETED.value,
                        session_id=session.id,
                        tenant_id=session.tenant_id,
                        metadata={
                            "completed_question_count": completed_count,
                            "followup_budget": {"used": session.max_followups, "max": session.max_followups},
                        },
                    )
                    completed_event = {
                        "event": "interview_completed",
                        "data": {"session": public_session(session), "report": public_report(report)},
                    }
                    events.append(completed_event)
                    InterviewRequestService.finish(request_row, {"events": events})
                    should_prepare_next = False
                else:
                    session = InterviewSessionRepository.transition(
                        session,
                        SessionStatus.PREPARING_QUESTION.value,
                        completed_question_count=completed_count,
                        current_difficulty=next_difficulty,
                        current_candidate_state=provisional_state,
                        current_interview_plan=provisional_plan,
                    )
                    should_prepare_next = True

            yield feedback_event
            if not should_prepare_next:
                yield completed_event
                return

            snapshot = await self._generate_question_for_action(session, action)
            self._ensure_operation_active(operation_id)
            with DB.atomic():
                session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
                if session.status != SessionStatus.PREPARING_QUESTION.value:
                    raise DomainError("state_conflict", "The session changed while preparing the next question.", http_status=409)
                next_round = InterviewSessionRepository.create_round(session, snapshot)
                next_round = InterviewSessionRepository.transition_round(next_round, RoundStatus.AWAITING_ANSWER.value)
                session = InterviewSessionRepository.transition(
                    session,
                    SessionStatus.AWAITING_ANSWER.value,
                    current_round_sequence=next_round.sequence,
                )
                next_event = {
                    "event": "next_question",
                    "data": {"session": public_session(session), "round": public_round(next_round, include_evaluation=False)},
                }
                events.append(next_event)
                InterviewRequestService.finish(request_row, {"events": events})
            yield next_event
        except DomainError as error:
            if operation_id and classify_failure(error).retryable:
                raise
            if request_row is not None and request_row.status == "processing":
                InterviewRequestService.fail(request_row, error)
            if error.code in PIPELINE_FAILURE_CODES:
                self._fail_session(session_id, tenant_id, user_id, error.code)
            raise
        except Exception as exc:
            LOGGER.exception("CS interview answer failed", extra={"session_id": session_id})
            error = DomainError("evaluation_failed", "The answer could not be evaluated safely.", http_status=500)
            if operation_id:
                raise error from exc
            if request_row is not None:
                InterviewRequestService.fail(request_row, error)
            self._fail_session(session_id, tenant_id, user_id, error.code)
            raise error from exc

    async def _resume_next_question(
        self,
        session: InterviewSession,
        tenant_id: str,
        user_id: str,
        request_row,
        operation_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Continue after evaluation committed but before the next question did.

        The completed round contains the deterministic planner action and score,
        so recovery never needs to repeat Judge or answer-state extraction.
        """

        completed_round = (
            InterviewRound.select()
            .where((InterviewRound.session_id == session.id) & (InterviewRound.status == RoundStatus.COMPLETED.value))
            .order_by(InterviewRound.sequence.desc())
            .first()
        )
        if completed_round is None or not completed_round.planner_actions:
            raise DomainError("state_conflict", "No completed evaluation checkpoint exists for recovery.", http_status=409)
        action = PlannerAction(**dict(completed_round.planner_actions[-1]))
        events = [
            {
                "event": "answer_received",
                "data": {"session_id": session.id, "round_id": completed_round.id, "state_version": max(0, session.state_version - 1)},
            },
            {"event": "evaluating", "data": {"session_id": session.id, "round_id": completed_round.id}},
            {
                "event": "feedback",
                "data": {
                    "round_id": completed_round.id,
                    "score": completed_round.score,
                    "verdict": completed_round.verdict,
                    "weak_point": completed_round.weak_point,
                    "feedback": completed_round.feedback,
                    "evaluation_summary": completed_round.evaluation_summary,
                    "final": True,
                    "next_difficulty": completed_round.next_difficulty,
                    "next_action": action.selected_action,
                    "next_action_reason": action.reason,
                },
            },
        ]
        for event in events:
            yield event
        snapshot = await self._generate_question_for_action(session, action)
        self._ensure_operation_active(operation_id)
        with DB.atomic():
            session = InterviewSessionRepository.get(session.id, tenant_id, user_id)
            if session.status != SessionStatus.PREPARING_QUESTION.value or InterviewSessionRepository.active_round(session.id):
                raise DomainError("state_conflict", "The next-question checkpoint was already changed.", http_status=409)
            next_round = InterviewSessionRepository.create_round(session, snapshot)
            next_round = InterviewSessionRepository.transition_round(next_round, RoundStatus.AWAITING_ANSWER.value)
            session = InterviewSessionRepository.transition(
                session,
                SessionStatus.AWAITING_ANSWER.value,
                current_round_sequence=next_round.sequence,
            )
            next_event = {
                "event": "next_question",
                "data": {"session": public_session(session), "round": public_round(next_round, include_evaluation=False)},
            }
            events.append(next_event)
            InterviewRequestService.finish(request_row, {"events": events})
        yield next_event

    def abort(
        self,
        session_id: str,
        tenant_id: str,
        user_id: str,
        expected_version: int,
        request_id: str,
    ) -> dict[str, Any]:
        digest = payload_hash({"expected_version": expected_version})
        with DB.atomic():
            session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
            request_row, replay = InterviewRequestService.begin(session.id, request_id, "abort", digest)
            if replay:
                return request_row.response["session"]
            session = InterviewSessionRepository.abort(session, expected_version=expected_version)
            response = public_session(session)
            InterviewRequestService.finish(request_row, {"session": response})
            return response

    async def execute_code(
        self,
        session_id: str,
        tenant_id: str,
        user_id: str,
        language: str,
        source_code: str,
        *,
        hidden: bool,
        request_id: str,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        language, source_code, _ = validate_code_request(language, source_code)
        digest = payload_hash({"language": language, "source_code": source_code, "hidden": hidden})
        with DB.atomic():
            session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
            request_row, replay = InterviewRequestService.begin(
                session.id,
                request_id,
                "code_submit" if hidden else "code_run",
                digest,
                operation_id=operation_id,
            )
            if replay:
                return request_row.response["submission"]
            existing_submission = CodeSubmission.get_or_none(CodeSubmission.operation_id == operation_id) if operation_id else None
            if session.status != SessionStatus.AWAITING_ANSWER.value:
                raise DomainError("not_awaiting_answer", "Code can only run while the interview awaits an answer.", http_status=409)
            round_ = InterviewSessionRepository.active_round(session.id)
            if round_ is None or round_.category != "leetcode":
                raise DomainError("not_coding_round", "The active round is not an algorithm question.", http_status=409)
            if existing_submission is None and CodeSubmission.select().where((CodeSubmission.round_id == round_.id) & (CodeSubmission.execution_status.in_(("queued", "running")))).exists():
                raise DomainError("code_execution_in_progress", "Another code execution is already running.", http_status=409)
            rubric = round_.evaluation_rubric if isinstance(round_.evaluation_rubric, dict) else {}
            code_spec = rubric.get("code_spec", {})
            tests = code_spec.get("hidden_tests" if hidden else "visible_tests", [])
            _, _, tests = validate_code_request(language, source_code, tests)
            submission = existing_submission or create_code_submission(
                tenant_id,
                user_id,
                session.id,
                round_.id,
                language,
                source_code,
                operation_id=operation_id,
            )
            CodeSubmission.update(execution_status="running", **_touch()).where(CodeSubmission.id == submission.id).execute()
        try:
            if operation_id:
                try:
                    result = await self.runner.execute(language, source_code, tests, execution_id=operation_id)
                except TypeError:
                    result = await self.runner.execute(language, source_code, tests)
            else:
                result = await self.runner.execute(language, source_code, tests)
        except DomainError as error:
            if operation_id and classify_failure(error).retryable:
                CodeSubmission.update(execution_status="queued", **_touch()).where(CodeSubmission.id == submission.id).execute()
                raise
            with DB.atomic():
                CodeSubmission.update(execution_status="runner_error", completed_at=utcnow(), **_touch()).where(CodeSubmission.id == submission.id).execute()
                InterviewRequestService.fail(request_row, error)
            raise
        except Exception as exc:
            LOGGER.exception(
                "CS interview code runner call failed safely",
                extra={"session_id": session.id, "round_id": round_.id, "submission_id": submission.id},
            )
            error = DomainError("runner_unavailable", "The isolated code runner is unavailable.", http_status=503)
            if operation_id:
                CodeSubmission.update(execution_status="queued", **_touch()).where(CodeSubmission.id == submission.id).execute()
                raise error from exc
            with DB.atomic():
                CodeSubmission.update(execution_status="runner_error", completed_at=utcnow(), **_touch()).where(CodeSubmission.id == submission.id).execute()
                InterviewRequestService.fail(request_row, error)
            raise error from exc
        LOGGER.info(
            "CS interview code execution completed",
            extra={
                "session_id": session.id,
                "round_id": round_.id,
                "submission_id": submission.id,
                "execution_status": result.get("status"),
                "code_execution_ms": result.get("runtime_ms"),
                "test_count": result.get("total_count"),
            },
        )
        result_status = str(result.get("status") or "unknown")
        RUNNER_EXECUTION.add(1, metric_attributes(language=language, result=result_status))
        if result_status == "timeout":
            RUNNER_TIMEOUT.add(1, metric_attributes(language=language, result="timeout"))
        TRACE_EMITTER.emit(
            TraceEventKind.CODE_EXECUTION_COMPLETED.value,
            session_id=session.id,
            tenant_id=session.tenant_id,
            round_id=round_.id,
            status="succeeded" if result_status == "completed" else "failed",
            error_code=None if result_status == "completed" else result_status,
            metadata={
                "language": language,
                "passed_count": result.get("passed_count"),
                "total_count": result.get("total_count"),
                "code_execution_ms": result.get("runtime_ms"),
            },
        )
        with DB.atomic():
            self._ensure_operation_active(operation_id)
            submission = CodeSubmission.get_by_id(submission.id)
            submission = complete_code_submission(submission, result, hidden=hidden)
            if hidden:
                InterviewRound.update(code_submission_id=submission.id, **_touch()).where((InterviewRound.id == round_.id) & (InterviewRound.active_guard == "active")).execute()
            response = public_code_submission(submission)
            InterviewRequestService.finish(request_row, {"submission": response})
        return response


_APPLICATION: InterviewApplication | None = None


def get_interview_application() -> InterviewApplication:
    global _APPLICATION
    if _APPLICATION is None:
        _APPLICATION = InterviewApplication()
    return _APPLICATION


def set_interview_application(application: InterviewApplication | None) -> None:
    global _APPLICATION
    _APPLICATION = application
