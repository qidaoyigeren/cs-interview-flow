"""Operations aggregations, governance actions and feedback for the admin surface.

All read paths are tenant-scoped and derive from the unified trace events plus
the immutable session/round snapshots -- never from candidate answers. Sensitive
detail (raw answers, reference answers, hidden tests) is exposed only through
``_redact`` (length + hash) unless a higher-permission path is used.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from api.apps.services.cs_interview.domain import DomainError
from api.apps.services.cs_interview.tracing import TRACE_EMITTER, TraceEventKind
from api.db.db_models import (
    CodeSubmission,
    InterviewFeedback,
    InterviewModelCall,
    InterviewOperation,
    InterviewReport,
    InterviewReviewAction,
    InterviewRound,
    InterviewSession,
    InterviewTraceEvent,
)
from api.db.services.interview_operation_service import audit
from common.misc_utils import get_uuid


def _redact(text: str | None, *, max_len: int = 16) -> str:
    """Return a length + hash summary of sensitive text without its content."""
    if not text:
        return ""
    digest = hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]
    return f"len={len(str(text))} hash={digest}"


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(q * len(ordered))))
    return ordered[index]


def quality_overview(*, tenant_id: str | None = None, since_hours: int = 24) -> dict[str, Any]:
    """Aggregate operational truth from traces plus owning persistence rows."""
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=max(1, since_hours))
    query = InterviewTraceEvent.select().where(InterviewTraceEvent.occurred_at >= since)
    if tenant_id:
        query = query.where(InterviewTraceEvent.tenant_id == tenant_id)

    events = list(query)
    stage_durations: dict[str, list[int]] = {}
    version_distribution: dict[str, dict[str, int]] = {}
    failed_by_stage: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    session_completed = session_failed = 0
    answer_received = 0
    evidence_rejected = 0
    retrieval_completed = 0
    duplicate_rejections = 0
    hidden_leakage_rejections = 0
    replay_total = 0
    replay_changed = 0

    for event in events:
        stage_counts[event.event_type] = stage_counts.get(event.event_type, 0) + 1
        if event.status == "failed":
            failed_by_stage[event.event_type] = failed_by_stage.get(event.event_type, 0) + 1
        if event.duration_ms is not None:
            stage_durations.setdefault(event.event_type, []).append(event.duration_ms)
            model_stage = str((event.metadata or {}).get("stage") or "")
            if event.event_type in {"model_call_completed", "model_call_failed"} and model_stage:
                stage_durations.setdefault(f"model:{model_stage}", []).append(event.duration_ms)
        if event.event_type == "session_completed":
            session_completed += 1
        elif event.event_type == "session_failed":
            session_failed += 1
        elif event.event_type == "answer_received":
            answer_received += 1
        elif event.event_type == "evidence_rejected":
            evidence_rejected += 1
        elif event.event_type == "retrieval_completed":
            retrieval_completed += 1
        elif event.event_type == "question_rejected":
            reason = str((event.metadata or {}).get("reason") or "")
            duplicate_rejections += int(reason == "semantic_duplicate")
            hidden_leakage_rejections += int(reason in {"question_answer_leakage", "followup_leakage"})
        elif event.event_type == "session_replayed":
            replay_total += 1
            replay_changed += int(str((event.metadata or {}).get("status") or "") != "deterministic")
        for key in ("planner_version", "prompt_version"):
            bucket = version_distribution.setdefault(key, {})
            value = getattr(event, key) or "unknown"
            bucket[value] = bucket.get(value, 0) + 1

    model_calls = InterviewModelCall.select().where(InterviewModelCall.create_date >= since)
    if tenant_id:
        model_calls = model_calls.where(InterviewModelCall.tenant_id == tenant_id)
    model_rows = list(model_calls)
    token_input = sum(row.prompt_tokens or 0 for row in model_rows)
    token_output = sum(row.completion_tokens or 0 for row in model_rows)
    estimated_cost = sum(row.estimated_cost or 0.0 for row in model_rows)
    cost_unknown_count = sum(1 for row in model_rows if row.cost_unknown)

    session_query = InterviewSession.select(InterviewSession.id).where(InterviewSession.create_date >= since)
    if tenant_id:
        session_query = session_query.where(InterviewSession.tenant_id == tenant_id)
    session_ids = [row.id for row in session_query]
    rounds = list(
        InterviewRound.select().where(
            (InterviewRound.session_id.in_(session_ids)) & (InterviewRound.status == "completed")
        )
    ) if session_ids else []
    reports = list(InterviewReport.select().where(InterviewReport.session_id.in_(session_ids))) if session_ids else []
    submissions = list(
        CodeSubmission.select().where(CodeSubmission.round_id.in_([row.id for row in rounds]))
    ) if rounds else []

    consistent_judges = 0
    for row in rounds:
        expected = "wrong_or_blank" if row.score in {0, 1} else "partial" if row.score in {2, 3} else "excellent" if row.score == 4 else None
        consistent_judges += int(expected is not None and row.verdict == expected)
    matrix_rows = [item for report in reports for item in (report.jd_verification_matrix or [])]
    covered_requirements = sum(
        1 for item in matrix_rows if str(item.get("verification_status") or item.get("status") or "untested") != "untested"
    )
    runner_failures = sum(1 for row in submissions if row.execution_status != "completed")
    operation_query = InterviewOperation.select().where(InterviewOperation.create_date >= since)
    if tenant_id:
        operation_query = operation_query.where(InterviewOperation.tenant_id == tenant_id)
    operations = list(operation_query)

    def success_rate(operation_type: str) -> float | None:
        terminal = [row for row in operations if row.operation_type == operation_type and row.status in {"completed", "failed"}]
        return round(sum(1 for row in terminal if row.status == "completed") / len(terminal), 4) if terminal else None

    start_durations = [
        int((row.completed_at - row.started_at).total_seconds() * 1000)
        for row in operations
        if row.operation_type == "start_interview" and row.status == "completed" and row.started_at and row.completed_at
    ]
    state_loss_count = sum(
        1 for row in operations if row.error_code in {"active_round_missing", "state_loss", "operation_checkpoint_missing"}
    )
    question_generated = stage_counts.get("question_generated", 0)
    cost_unknown_rate = round(cost_unknown_count / len(model_rows), 4) if model_rows else None
    slo_metrics = {
        "session_created_success": success_rate("start_interview"),
        "answer_request_success": success_rate("evaluate_answer"),
        "state_loss_rate": round(state_loss_count / len(operations), 4) if operations else None,
        "duplicate_question_ratio": round(duplicate_rejections / question_generated, 4) if question_generated else None,
        "hidden_answer_leakage_count": hidden_leakage_rejections,
        "replay_inconsistency_ratio": round(replay_changed / replay_total, 4) if replay_total else None,
        "first_question_p95_ms": _percentile(start_durations, 0.95),
        "judge_p95_ms": _percentile(stage_durations.get("model:judge", []), 0.95),
        "runner_failure_rate": round(runner_failures / len(submissions), 4) if submissions else None,
        "cost_unknown_rate": cost_unknown_rate,
    }
    sessions = session_completed + session_failed
    result = {
        "window_hours": since_hours,
        "session_count": sessions,
        "session_success_rate": round(session_completed / sessions, 4) if sessions else None,
        "session_failure_count": session_failed,
        "answer_request_count": answer_received,
        "stage_failure_rates": {
            name: round(failed_by_stage.get(name, 0) / count, 4) for name, count in stage_counts.items() if count
        },
        "latency_p50_p95": {
            name: {"p50": _percentile(durations, 0.5), "p95": _percentile(durations, 0.95)}
            for name, durations in stage_durations.items()
        },
        "tokens": {"input": token_input, "output": token_output},
        "estimated_cost_usd": round(estimated_cost, 4),
        "cost_unknown_count": cost_unknown_count,
        "evidence_rejected_count": evidence_rejected,
        "retrieval_count": retrieval_completed,
        "evidence_refusal_rate": round(evidence_rejected / retrieval_completed, 4) if retrieval_completed else None,
        "followup_rate": round(sum(1 for row in rounds if row.followup_count > 0) / len(rounds), 4) if rounds else None,
        "judge_consistency_rate": round(consistent_judges / len(rounds), 4) if rounds else None,
        "jd_requirement_coverage": round(covered_requirements / len(matrix_rows), 4) if matrix_rows else None,
        "runner_failure_rate": round(runner_failures / len(submissions), 4) if submissions else None,
        "slo_metrics": slo_metrics,
        "version_distribution": version_distribution,
    }
    from api.apps.services.cs_interview.slo import evaluate_alerts

    result["alerts"] = evaluate_alerts(slo_metrics)
    return result


def list_admin_sessions(*, tenant_id: str | None = None, page: int = 1, page_size: int = 20, status: str | None = None) -> list[dict[str, Any]]:
    query = InterviewSession.select()
    if tenant_id:
        query = query.where(InterviewSession.tenant_id == tenant_id)
    if status:
        query = query.where(InterviewSession.status == status)
    rows = query.order_by(InterviewSession.create_time.desc()).paginate(max(1, page), max(1, min(100, page_size)))
    return [
        {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "status": row.status,
            "planner_version": row.planner_version,
            "prompt_version": row.prompt_version,
            "current_difficulty": row.current_difficulty,
            "completed_question_count": row.completed_question_count,
            "failure_code": row.failure_code,
            "created_at": row.create_date,
        }
        for row in rows
    ]


def session_audit(session_id: str, tenant_id: str) -> dict[str, Any]:
    """Read-only audit trail for one session: timeline + planner decision summaries."""
    session = InterviewSession.get_or_none((InterviewSession.id == session_id) & (InterviewSession.tenant_id == tenant_id))
    if session is None:
        raise DomainError("session_not_found", "Session not found.", http_status=404)
    timeline = [
        {
            "event_type": row.event_type,
            "occurred_at": row.occurred_at.isoformat(),
            "status": row.status,
            "error_code": row.error_code,
            "round_id": row.round_id,
            "planner_version": row.planner_version,
            "prompt_version": row.prompt_version,
            "duration_ms": row.duration_ms,
            "metadata": row.metadata,
        }
        for row in InterviewTraceEvent.select()
        .where((InterviewTraceEvent.session_id == session_id) & (InterviewTraceEvent.tenant_id == tenant_id))
        .order_by(InterviewTraceEvent.occurred_at)
    ]
    rounds = []
    for row in InterviewRound.select().where(InterviewRound.session_id == session_id).order_by(InterviewRound.sequence):
        actions = row.planner_actions or []
        evaluations = (row.evidence_evaluation or {}).get("evaluations") or []
        evidence_audit = [
            {
                "answer_sequence": item.get("answer_sequence"),
                "score": (item.get("evaluation") or {}).get("scorer", {}).get("score"),
                "matched_anchor": (item.get("evaluation") or {}).get("scorer", {}).get("matched_anchor"),
                "confidence": (item.get("evaluation") or {}).get("scorer", {}).get("confidence"),
                "low_confidence": bool((item.get("evaluation") or {}).get("low_confidence")),
                "consistency_passed": (item.get("evaluation") or {}).get("validator", {}).get("passed"),
                "evidence_span_ids": (item.get("evaluation") or {}).get("scorer", {}).get("evidence_span_ids"),
                "span_texts": [
                    span.get("text")
                    for span_id in (item.get("evaluation") or {}).get("scorer", {}).get("evidence_span_ids", [])
                    for span in (item.get("evaluation") or {}).get("extraction", {}).get("answer_spans", [])
                    if span.get("span_id") == span_id
                ],
            }
            for item in evaluations
        ]
        rounds.append(
            {
                "sequence": row.sequence,
                "topic": row.topic,
                "competency_id": row.competency_id,
                "question_kind": row.question_kind or "adaptive",
                "anchor_group_id": row.anchor_group_id,
                "rubric_version": row.rubric_version,
                "category": row.category,
                "difficulty": row.difficulty,
                "question_id": row.question_id,
                "score": row.score,
                "verdict": row.verdict,
                "target_requirement_id": row.target_requirement_id,
                "evidence_versions": row.evidence_versions,
                "model_version": row.model_version,
                "prompt_version": row.prompt_version,
                "planner_actions": [
                    {
                        "selected_action": item.get("selected_action"),
                        "target_requirement_id": item.get("target_requirement_id"),
                        "target_topic": item.get("target_topic"),
                        "question_kind": item.get("question_kind"),
                        "competency_id": item.get("competency_id"),
                        "action_factors": item.get("action_factors"),
                        "reason": _redact(item.get("reason")),
                        "decision_audit": item.get("decision_audit"),
                    }
                    for item in actions
                ],
                "evidence_evaluation": evidence_audit,
                # Answers are never exposed in full -- only a redacted summary.
                "answer_summary": _redact((row.candidate_answers or [{}])[-1].get("answer") if row.candidate_answers else ""),
            }
        )
    return {
        "session_id": session_id,
        "status": session.status,
        "state_version": session.state_version,
        "planner_version": session.planner_version,
        "prompt_version": session.prompt_version,
        "failure_code": session.failure_code,
        "timeline": timeline,
        "rounds": rounds,
        "created_at": session.create_date.isoformat(),
    }


def high_failure_questions(*, tenant_id: str | None = None, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
    query = InterviewRound.select().where(InterviewRound.status == "completed")
    if tenant_id:
        query = query.where(InterviewRound.session_id.in_(InterviewSession.select(InterviewSession.id).where(InterviewSession.tenant_id == tenant_id)))
    counts: dict[str, dict[str, Any]] = {}
    for row in query.paginate(max(1, page), max(1, min(100, page_size * 10))):
        key = str(row.question_id or "unknown")
        entry = counts.setdefault(key, {"question_id": key, "topic": row.topic, "attempts": 0, "failures": 0, "latest_score": None})
        entry["attempts"] += 1
        if row.score is not None and row.score <= 1:
            entry["failures"] += 1
        if row.score is not None:
            entry["latest_score"] = row.score
    ordered = sorted(counts.values(), key=lambda item: (-item["failures"], item["question_id"]))
    return ordered[: max(1, min(100, page_size))]


def _tenant_rounds(tenant_id: str):
    session_ids = InterviewSession.select(InterviewSession.id).where(InterviewSession.tenant_id == tenant_id)
    return InterviewRound.select().where(InterviewRound.session_id.in_(session_ids))


def _round_evidence_ids(round_: InterviewRound) -> set[str]:
    return {
        str(item.get("evidence_id"))
        for item in [*(round_.retrieval_evidence or []), *(round_.evidence_versions or [])]
        if item.get("evidence_id")
    }


def blocked_resource_ids(tenant_id: str, resource_type: str) -> set[str]:
    """Return resources whose latest tenant-scoped governance action blocks use."""
    latest: dict[str, str] = {}
    rows = (
        InterviewReviewAction.select()
        .where(
            (InterviewReviewAction.tenant_id == tenant_id)
            & (InterviewReviewAction.resource_type == resource_type)
        )
        .order_by(InterviewReviewAction.create_date.asc(), InterviewReviewAction.id.asc())
    )
    for row in rows:
        latest[row.resource_id] = row.action
    return {resource_id for resource_id, action in latest.items() if action in {"mark_bad", "take_down"}}


def record_review(*, reviewer_id_hash: str, resource_type: str, resource_id: str, action: str, comment: str, tenant_id: str) -> dict[str, Any]:
    if resource_type not in {"question", "evidence", "session"}:
        raise DomainError("invalid_review_resource", "Review resource must be question, evidence or session.", http_status=400)
    if action not in {"mark_bad", "take_down", "review"}:
        raise DomainError("invalid_review_action", "Review action must be mark_bad, take_down or review.", http_status=400)
    resource_id = str(resource_id).strip()[:128]
    if not resource_id:
        raise DomainError("invalid_review_resource", "Review resource id is required.", http_status=400)
    affected_session_ids: set[str] = set()
    if resource_type == "session":
        session = InterviewSession.get_or_none(
            (InterviewSession.id == resource_id) & (InterviewSession.tenant_id == tenant_id)
        )
        if session is None:
            raise DomainError("review_resource_not_found", "Review resource not found.", http_status=404)
        affected_session_ids.add(session.id)
    else:
        matched = []
        for round_ in _tenant_rounds(tenant_id):
            if resource_type == "question" and round_.question_id == resource_id or resource_type == "evidence" and resource_id in _round_evidence_ids(round_):
                matched.append(round_)
        if not matched:
            raise DomainError("review_resource_not_found", "Review resource not found.", http_status=404)
        affected_session_ids.update(row.session_id for row in matched)
    row = InterviewReviewAction.create(
        id=get_uuid(),
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        reviewer_id_hash=reviewer_id_hash,
        comment=str(comment)[:2000],
        **_timestamps(),
    )
    audit(
        tenant_id,
        reviewer_id_hash,
        f"review_{action}",
        resource_type,
        resource_id[:32],
        "completed",
        {"review_action_id": row.id, "affected_session_count": len(affected_session_ids)},
    )
    return {
        "id": row.id,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "action": row.action,
        "blocked": action in {"mark_bad", "take_down"},
        "affected_session_count": len(affected_session_ids),
        "reevaluation_required": action in {"mark_bad", "take_down"} and bool(affected_session_ids),
    }


def submit_feedback(*, tenant_id: str, user_id: str, session_id: str, kind: str, message: str, **versions: str | None) -> dict[str, Any]:
    allowed = {"irrelevant_question", "unclear_wording", "unfair_scoring", "stale_evidence", "technical_error", "privacy_issue"}
    if kind not in allowed:
        raise DomainError("invalid_feedback_kind", f"Feedback kind must be one of {sorted(allowed)}.", http_status=400)
    session = InterviewSession.get_or_none((InterviewSession.id == session_id) & (InterviewSession.tenant_id == tenant_id) & (InterviewSession.user_id == user_id))
    if session is None:
        raise DomainError("session_not_found", "Session not found.", http_status=404)
    round_id = str(versions.get("round_id") or "").strip()
    round_: InterviewRound | None = None
    if round_id:
        round_ = InterviewRound.get_or_none(
            (InterviewRound.id == round_id) & (InterviewRound.session_id == session.id)
        )
        if round_ is None:
            raise DomainError("feedback_round_not_found", "Feedback round does not belong to this session.", http_status=404)
    if (versions.get("question_id") or versions.get("evidence_id")) and round_ is None:
        raise DomainError("feedback_round_required", "Question or evidence feedback requires a round_id.", http_status=400)
    evidence_id = str(versions.get("evidence_id") or "").strip() or None
    if evidence_id and round_ is not None and evidence_id not in _round_evidence_ids(round_):
        raise DomainError("feedback_evidence_not_found", "Feedback evidence does not belong to this round.", http_status=404)
    row = InterviewFeedback.create(
        id=get_uuid(),
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        round_id=round_.id if round_ else None,
        question_id=round_.question_id if round_ else None,
        evidence_id=evidence_id,
        kind=kind,
        message=str(message)[:2000],
        model=round_.model_version if round_ else None,
        prompt_version=round_.prompt_version if round_ else session.prompt_version,
        planner_version=session.planner_version,
        status="open",
        **_timestamps(),
    )
    audit(tenant_id, user_id, "user_feedback", "interview_feedback", row.id, "received", {"kind": kind, "session_id": session_id})
    TRACE_EMITTER.emit(
        TraceEventKind.USER_FEEDBACK_RECEIVED.value,
        session_id=session.id,
        tenant_id=tenant_id,
        round_id=round_.id if round_ else None,
        metadata={
            "kind": kind,
            "feedback_id": row.id,
            "question_id": round_.question_id if round_ else None,
            "evidence_id": evidence_id,
        },
        immediate=True,
    )
    return {"id": row.id, "kind": kind, "status": "open", "session_id": session_id}


def list_feedback(*, tenant_id: str, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
    rows = (
        InterviewFeedback.select()
        .where(InterviewFeedback.tenant_id == tenant_id)
        .order_by(InterviewFeedback.create_time.desc())
        .paginate(max(1, page), max(1, min(100, page_size)))
    )
    return [
        {
            "id": row.id,
            "session_id": row.session_id,
            "round_id": row.round_id,
            "question_id": row.question_id,
            "evidence_id": row.evidence_id,
            "kind": row.kind,
            "status": row.status,
            "message": row.message,
            "model": row.model,
            "prompt_version": row.prompt_version,
            "planner_version": row.planner_version,
            "created_at": row.create_date,
        }
        for row in rows
    ]


def _timestamps():
    now = datetime.now(UTC).replace(tzinfo=None)
    millis = int(now.timestamp() * 1000)
    return {"create_time": millis, "update_time": millis}
