"""Read-only planner replay for CS interview sessions.

Replay rebuilds the planner inputs exclusively from immutable session snapshots
(initial_interview_plan, initial_candidate_state, profile/job/match/knowledge
snapshots) and the completed InterviewRound rows. It never reads back mutated
Profile / Job / Resume / knowledge-config rows, and it never writes to the
database -- the original session is untouched.

Each completed round contributes one question decision and one decision after
every stored answer:

* ``question`` -- the action that created the round's question, compared
  against ``choose_planner_action`` re-run on the pre-round state.
* ``after_answer:N`` -- the action recorded after answer N, including every
  intermediate follow-up, compared against ``choose_after_answer_action``.

The comparison ignores the audit record (decision_audit) and cosmetic fields,
focusing on the decision essence: selected_action, target_requirement_id,
target_topic and target_contradiction_id.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from api.apps.services.cs_interview.domain import (
    SUPPORTED_PLANNER_VERSIONS,
    JudgeResult,
    PlannerAction,
    PlannerActionKind,
    choose_after_answer_action_versioned,
    choose_planner_action_versioned,
    compute_next_difficulty,
    merge_candidate_state,
    update_interview_plan,
)


def _judge_from_evaluation(evaluation: dict[str, Any]) -> JudgeResult:
    return JudgeResult(**{name: evaluation[name] for name in JudgeResult.__dataclass_fields__ if name in evaluation})


def _answer_state_at(round_data: dict[str, Any], answer_index: int) -> dict[str, Any]:
    extractions = (round_data.get("answer_state") or {}).get("extractions") or []
    if answer_index < len(extractions):
        return dict(extractions[answer_index].get("state") or {})
    return {}


def _targeted_claim_facts(action: dict[str, Any]) -> list[str]:
    if action.get("selected_action") == PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value:
        claim = str((action.get("supporting_state") or {}).get("target_claim_fact") or "").strip()
        return [claim] if claim else []
    return []


def _project_target(action: dict[str, Any], round_data: dict[str, Any]) -> dict[str, Any] | None:
    """Rebuild the (project, claim, dimension) target from the stored action."""
    project_id = str(action.get("target_project_id") or "")
    claim_id = str(action.get("target_claim_id") or "")
    if not project_id or not claim_id:
        return None
    return {
        "project_id": project_id,
        "claim_id": claim_id,
        "dimension": str(action.get("project_dimension") or ""),
        "claim_text": str((action.get("supporting_state") or {}).get("target_claim_fact") or "")[:500],
        "followup_depth": int(action.get("project_followup_depth") or 0),
        "question_id": str(round_data.get("question_id") or ""),
    }


def _resolved_contradiction_ids(action: dict[str, Any]) -> list[str]:
    if action.get("selected_action") == PlannerActionKind.RESOLVE_CONTRADICTION.value:
        cid = str(
            (action.get("supporting_state") or {}).get("target_contradiction_id")
            or action.get("target_contradiction_id")
            or ""
        ).strip()
        return [cid] if cid else []
    return []


def _stored_identity(original: dict[str, Any]) -> dict[str, Any]:
    return {
        "selected_action": str(original.get("selected_action") or ""),
        "target_requirement_id": original.get("target_requirement_id"),
        "target_topic": original.get("target_topic"),
        "target_contradiction_id": str(original.get("target_contradiction_id") or ""),
        "target_project_id": str(original.get("target_project_id") or ""),
        "target_claim_id": str(original.get("target_claim_id") or ""),
        "project_dimension": str(original.get("project_dimension") or ""),
    }


def _replayed_identity(action: PlannerAction) -> dict[str, Any]:
    return {
        "selected_action": action.selected_action,
        "target_requirement_id": action.target_requirement_id,
        "target_topic": action.target_topic,
        "target_contradiction_id": action.target_contradiction_id,
        "target_project_id": str(action.target_project_id or ""),
        "target_claim_id": str(action.target_claim_id or ""),
        "project_dimension": str(action.project_dimension or ""),
    }


def _compare(decision_point: str, round_sequence: int, original: dict[str, Any], replayed: PlannerAction) -> dict[str, Any]:
    original_identity = _stored_identity(original)
    replayed_identity = _replayed_identity(replayed)
    return {
        "round_sequence": round_sequence,
        "decision_point": decision_point,
        "original": original_identity,
        "replayed": replayed_identity,
        "outcome": "deterministic" if original_identity == replayed_identity else "changed",
    }


def _as_round_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return dict(row.__data__)


def replay_planner_decision(
    *,
    planner_version: str,
    plan: list[dict[str, Any]],
    candidate_state: dict[str, Any],
    history: list[dict[str, Any]],
    stored_action: dict[str, Any],
    remaining_question_budget: int,
    current_difficulty: str,
    competency_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay one planner checkpoint using the same production dispatcher."""
    replayed = choose_planner_action_versioned(
        planner_version,
        deepcopy(plan),
        deepcopy(candidate_state),
        deepcopy(history),
        remaining_question_budget=remaining_question_budget,
        current_difficulty=current_difficulty,
        competency_snapshot=deepcopy(competency_snapshot),
    )
    return _compare("question", 0, stored_action, replayed)


def replay_session(
    session: Any,
    rounds: list[Any],
    *,
    planner_version: str = "latest",
    emit_trace: bool = False,
) -> dict[str, Any]:
    """Re-run the planner over a session's immutable inputs and compare."""
    resolved_version = str(session.planner_version) if planner_version in {None, "", "latest"} else str(planner_version)
    if resolved_version not in SUPPORTED_PLANNER_VERSIONS:
        return {
            "session_id": session.id,
            "requested_planner_version": planner_version,
            "session_planner_version": session.planner_version,
            "status": "unsupported_version",
            "decisions": [],
            "deterministic_count": 0,
            "total_count": 0,
            "deterministic_ratio": 0.0,
            "final_project_claim_state": {},
        }

    profile = dict(session.profile_snapshot or {})
    plan = [dict(item) for item in (session.initial_interview_plan or [])]
    candidate_state = dict(session.initial_candidate_state or {})
    competency_snapshot = dict(getattr(session, "competency_snapshot", None) or {})
    history: list[dict[str, Any]] = []
    difficulty = str(profile.get("initial_difficulty") or "medium")
    max_questions = int(session.max_questions or 0)
    max_followups = int(session.max_followups or 0)
    decisions: list[dict[str, Any]] = []
    completed = [
        data
        for row in rounds
        if (data := _as_round_dict(row)).get("status") in {None, "completed"}
    ]

    for round_data in completed:
        remaining_before = max_questions - len(history)
        round_sequence = int(round_data.get("sequence") or len(history) + 1)
        actions = list(round_data.get("planner_actions") or [])

        original_question = actions[0] if actions else None
        if original_question is not None:
            replayed_question = choose_planner_action_versioned(
                resolved_version,
                plan,
                candidate_state,
                history,
                remaining_question_budget=remaining_before,
                current_difficulty=difficulty,
                competency_snapshot=competency_snapshot,
            )
            decisions.append(_compare("question", round_sequence, original_question, replayed_question))

        requirement_id = round_data.get("target_requirement_id")
        competency_id = str(round_data.get("competency_id") or round_data.get("topic") or "")
        rubric = ((competency_snapshot or {}).get("rubrics") or {}).get(competency_id) or {}
        required_score = max(2, min(4, int(rubric.get("required_score") or 3)))
        answers = list(round_data.get("candidate_answers") or [])
        for answer_index, answer in enumerate(answers):
            evaluation = answer.get("evaluation")
            if not isinstance(evaluation, dict) or answer_index + 1 >= len(actions):
                continue

            judge = _judge_from_evaluation(evaluation)
            answer_state = _answer_state_at(round_data, answer_index)
            prompting_action = actions[answer_index]
            resolved_ids = _resolved_contradiction_ids(prompting_action) if judge.score >= 2 else []
            provisional_state = merge_candidate_state(
                dict(candidate_state),
                answer_state,
                judge,
                requirement_id=requirement_id,
                target_topic=str(round_data.get("topic") or ""),
                completed=True,
                required_score=required_score,
                targeted_claim_facts=_targeted_claim_facts(prompting_action),
                resolved_contradiction_ids=resolved_ids,
                project_target=_project_target(prompting_action, round_data),
            )
            provisional_plan = update_interview_plan(plan, requirement_id, score=judge.score, completed=True, required_score=required_score)
            previous_score = history[-1].get("score") if history else None
            next_difficulty = compute_next_difficulty(difficulty, judge.score, previous_score)
            round_at_answer = {
                **round_data,
                "candidate_answers": answers[: answer_index + 1],
                "followup_count": answer_index,
            }
            replayed_action = choose_after_answer_action_versioned(
                resolved_version,
                provisional_plan,
                provisional_state,
                answer_state,
                judge,
                round_at_answer,
                [*history, round_at_answer],
                remaining_question_budget=max_questions - len(history) - 1,
                max_followups=max_followups,
                current_difficulty=next_difficulty,
                competency_snapshot=competency_snapshot,
            )
            original_action = actions[answer_index + 1]
            decisions.append(
                _compare(f"after_answer:{answer_index + 1}", round_sequence, original_action, replayed_action)
            )

            is_followup = (
                original_action.get("selected_action")
                in {
                    PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value,
                    PlannerActionKind.RESOLVE_CONTRADICTION.value,
                }
                and original_action.get("target_topic") == round_data.get("topic")
                and answer_index + 1 < len(answers)
            )
            if is_followup:
                candidate_state = merge_candidate_state(
                    dict(candidate_state),
                    answer_state,
                    judge,
                    requirement_id=requirement_id,
                    target_topic=str(round_data.get("topic") or ""),
                    completed=False,
                    required_score=required_score,
                    resolved_contradiction_ids=resolved_ids,
                    project_target=_project_target(prompting_action, round_data),
                )
                candidate_state["next_action_reason"] = str(original_action.get("reason") or "")
                plan = update_interview_plan(plan, requirement_id, score=None, completed=False, required_score=required_score)
                continue

            provisional_state["next_action_reason"] = str(original_action.get("reason") or "")
            candidate_state = provisional_state
            plan = provisional_plan
            difficulty = str(round_data.get("next_difficulty") or next_difficulty)
            history.append(round_data)
            break

    total = len(decisions)
    deterministic_count = sum(1 for item in decisions if item["outcome"] == "deterministic")
    if emit_trace:
        from api.apps.services.cs_interview.tracing import TRACE_EMITTER, TraceEventKind

        TRACE_EMITTER.emit(
            TraceEventKind.SESSION_REPLAYED.value,
            session_id=session.id,
            tenant_id=session.tenant_id,
            replay=True,
            metadata={
                "planner_version": resolved_version,
                "deterministic_count": deterministic_count,
                "total_count": total,
                "status": "deterministic" if total and deterministic_count == total else "changed",
            },
            immediate=True,
        )
    return {
        "session_id": session.id,
        "requested_planner_version": planner_version,
        "session_planner_version": session.planner_version,
        "status": "deterministic" if total and deterministic_count == total else "changed",
        "decisions": decisions,
        "deterministic_count": deterministic_count,
        "total_count": total,
        "deterministic_ratio": round(deterministic_count / total, 4) if total else 0.0,
        "final_project_claim_state": deepcopy(candidate_state.get("project_claim_state") or {}),
    }
