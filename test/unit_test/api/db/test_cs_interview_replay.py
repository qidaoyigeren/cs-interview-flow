"""Read-only planner replay tests (determinism, version handling, no writes)."""

from __future__ import annotations

import types

from api.apps.services.cs_interview.domain import (
    PLANNER_VERSION,
    PlannerActionKind,
    choose_after_answer_action,
    choose_planner_action,
    initial_candidate_state,
)
from api.apps.services.cs_interview.replay import replay_session
from api.apps.services.cs_interview.tracing import TRACE_EMITTER
from api.db.db_models import InterviewSession


def _plan():
    return [
        {
            "requirement_id": "req-go",
            "topic_id": "go.runtime",
            "priority": 2,
            "objective": "验证 Go",
            "preferred_question_type": "theory",
            "target_difficulty": "medium",
            "verification_strategy": "verify_resume_claim",
            "status": "pending",
            "attempt_count": 0,
        },
        {
            "requirement_id": "req-algo",
            "topic_id": "algorithm.core",
            "priority": 1,
            "objective": "验证算法",
            "preferred_question_type": "coding",
            "target_difficulty": "medium",
            "verification_strategy": "verify_jd_requirement",
            "status": "pending",
            "attempt_count": 0,
        },
    ]


def _judge_evaluation(score=3, needs_followup=False):
    return {
        "score": score,
        "verdict": "partial" if score in {2, 3} else "excellent",
        "covered_points": ["p1"],
        "missing_points": [],
        "factual_errors": [],
        "needs_followup": needs_followup,
        "followup_focus": "focus" if needs_followup else "",
        "weak_point": "" if not needs_followup else "weak",
        "feedback": "feedback",
        "evaluation_summary": "summary",
        "confidence": 0.9,
    }


def _empty_answer_state():
    return {"newly_claimed_facts": [], "contradictions": [], "project_facts": []}


def _session_obj(plan, *, max_questions=2, max_followups=2):
    return types.SimpleNamespace(
        id="session-replay",
        tenant_id="tenant-1",
        planner_version=PLANNER_VERSION,
        profile_snapshot={"target_role": "go_backend", "initial_difficulty": "medium"},
        initial_interview_plan=[dict(item) for item in plan],
        initial_candidate_state=initial_candidate_state(),
        max_questions=max_questions,
        max_followups=max_followups,
    )


def _round_dict(sequence, topic, requirement_id, score, judge_eval, question_action, final_action, answer_state=None):
    return {
        "sequence": sequence,
        "topic": topic,
        "target_requirement_id": requirement_id,
        "score": score,
        "next_difficulty": "medium",
        "followup_count": 0,
        "question_type": "theory",
        "planner_actions": [question_action, final_action],
        "candidate_answers": [{"kind": "initial", "answer": "answer", "evaluation": judge_eval}],
        "answer_state": {"extractions": [{"answer_sequence": 1, "state": answer_state or _empty_answer_state()}]},
    }


def _asdict_action(action):
    import dataclasses

    return dataclasses.asdict(action)


def _build_two_round_scenario():
    """Build a session + rounds whose stored actions came from the real planner."""
    plan = _plan()
    state = initial_candidate_state()
    history = []

    # Round 1 question action.
    q1 = choose_planner_action(plan, state, history, remaining_question_budget=2, current_difficulty="medium")
    judge1 = _judge_evaluation(score=3)
    answer_state1 = _empty_answer_state()
    # Forward-simulate round 1 state/plan as the live service does.
    from api.apps.services.cs_interview.domain import merge_candidate_state, update_interview_plan

    state1 = merge_candidate_state(
        state,
        answer_state1,
        _judge(judge1),
        requirement_id="req-go",
        target_topic="go.runtime",
        completed=True,
    )
    plan1 = update_interview_plan(plan, "req-go", score=3, completed=True)
    history1 = [{"topic": "go.runtime", "target_requirement_id": "req-go", "score": 3}]
    final1 = choose_after_answer_action(
        plan1,
        state1,
        answer_state1,
        _judge(judge1),
        {"topic": "go.runtime", "target_requirement_id": "req-go", "followup_count": 0, "question_type": "theory"},
        history1,
        remaining_question_budget=1,
        max_followups=2,
        current_difficulty="medium",
    )

    # Round 2 question action.
    q2 = choose_planner_action(plan1, state1, history1, remaining_question_budget=1, current_difficulty="medium")
    judge2 = _judge_evaluation(score=3)
    answer_state2 = _empty_answer_state()
    state2 = merge_candidate_state(
        state1,
        answer_state2,
        _judge(judge2),
        requirement_id=q2.target_requirement_id,
        target_topic=q2.target_topic,
        completed=True,
    )
    plan2 = update_interview_plan(plan1, q2.target_requirement_id, score=3, completed=True)
    history2 = [*history1, {"topic": q2.target_topic, "target_requirement_id": q2.target_requirement_id, "score": 3}]
    final2 = choose_after_answer_action(
        plan2,
        state2,
        answer_state2,
        _judge(judge2),
        {"topic": q2.target_topic, "target_requirement_id": q2.target_requirement_id, "followup_count": 0, "question_type": "coding"},
        history2,
        remaining_question_budget=0,
        max_followups=2,
        current_difficulty="medium",
    )

    round1 = _round_dict(1, "go.runtime", "req-go", 3, judge1, _asdict_action(q1), _asdict_action(final1), answer_state1)
    round2 = _round_dict(
        2,
        str(q2.target_topic),
        q2.target_requirement_id,
        3,
        judge2,
        _asdict_action(q2),
        _asdict_action(final2),
        answer_state2,
    )
    return _session_obj(plan), [round1, round2]


def _judge(evaluation):
    from api.apps.services.cs_interview.domain import JudgeResult

    return JudgeResult(
        score=int(evaluation["score"]),
        verdict=evaluation["verdict"],
        covered_points=list(evaluation.get("covered_points") or []),
        missing_points=list(evaluation.get("missing_points") or []),
        factual_errors=list(evaluation.get("factual_errors") or []),
        needs_followup=bool(evaluation.get("needs_followup")),
        followup_focus=str(evaluation.get("followup_focus") or ""),
        weak_point=str(evaluation.get("weak_point") or ""),
        feedback=str(evaluation.get("feedback") or ""),
        evaluation_summary=str(evaluation.get("evaluation_summary") or ""),
        confidence=float(evaluation.get("confidence") or 0),
    )


def test_replay_is_deterministic_for_real_planner_decisions():
    TRACE_EMITTER.clear()
    session, rounds = _build_two_round_scenario()
    result = replay_session(session, rounds)
    assert result["status"] == "deterministic"
    assert result["total_count"] == 4  # question + after_answer per round
    assert result["deterministic_count"] == 4
    assert result["deterministic_ratio"] == 1.0


def test_replay_uses_session_version_and_rejects_unsupported_version():
    TRACE_EMITTER.clear()
    session, rounds = _build_two_round_scenario()
    result = replay_session(session, rounds, planner_version=PLANNER_VERSION)
    assert result["status"] == "deterministic"
    unknown = replay_session(session, rounds, planner_version="cs-interview-planner-v999")
    assert unknown["status"] == "unsupported_version"
    assert unknown["decisions"] == []


def test_replay_never_mutates_session_or_rounds():
    TRACE_EMITTER.clear()
    session, rounds = _build_two_round_scenario()
    plan_before = [dict(item) for item in session.initial_interview_plan]
    rounds_before = [dict(round_item) for round_item in rounds]
    replay_session(session, rounds)
    assert session.initial_interview_plan == plan_before
    assert rounds == rounds_before


def test_replay_detects_changed_decision_when_stored_action_differs():
    TRACE_EMITTER.clear()
    session, rounds = _build_two_round_scenario()
    # Corrupt the stored final decision of round 1 to a different action.
    rounds[0]["planner_actions"][-1] = {
        "selected_action": PlannerActionKind.FINISH_INTERVIEW.value,
        "target_requirement_id": None,
        "target_topic": None,
        "target_contradiction_id": "",
    }
    result = replay_session(session, rounds)
    assert result["status"] == "changed"
    assert any(item["outcome"] == "changed" for item in result["decisions"])


def test_replay_uses_a_persisted_initial_candidate_state_snapshot():
    assert "initial_candidate_state" in InterviewSession._meta.fields


def test_replay_covers_every_intermediate_followup_decision():
    from api.apps.services.cs_interview.domain import merge_candidate_state, update_interview_plan

    plan = [_plan()[0]]
    state = initial_candidate_state()
    question_action = choose_planner_action(
        plan,
        state,
        [],
        remaining_question_budget=1,
        current_difficulty="medium",
    )
    claim_state = {
        **_empty_answer_state(),
        "newly_claimed_facts": [
            {
                "fact": "我使用 pprof 定位过线上 CPU 热点",
                "topic_ids": ["go.runtime"],
                "source_span": "pprof",
                "confidence": 0.9,
                "status": "claimed",
            }
        ],
    }
    first_judge_data = _judge_evaluation(score=3)
    first_judge = _judge(first_judge_data)
    provisional_state = merge_candidate_state(
        state,
        claim_state,
        first_judge,
        requirement_id="req-go",
        target_topic="go.runtime",
        completed=True,
    )
    provisional_plan = update_interview_plan(plan, "req-go", score=3, completed=True)
    first_action = choose_after_answer_action(
        provisional_plan,
        provisional_state,
        claim_state,
        first_judge,
        {"topic": "go.runtime", "target_requirement_id": "req-go", "followup_count": 0, "question_type": "theory"},
        [{"topic": "go.runtime", "target_requirement_id": "req-go", "followup_count": 0, "question_type": "theory"}],
        remaining_question_budget=0,
        max_followups=2,
        current_difficulty="medium",
    )
    assert first_action.selected_action == PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value

    state_after_followup = merge_candidate_state(
        state,
        claim_state,
        first_judge,
        requirement_id="req-go",
        target_topic="go.runtime",
        completed=False,
    )
    state_after_followup["next_action_reason"] = first_action.reason
    plan_after_followup = update_interview_plan(plan, "req-go", score=None, completed=False)
    second_judge_data = _judge_evaluation(score=4)
    second_judge = _judge(second_judge_data)
    final_state = merge_candidate_state(
        state_after_followup,
        _empty_answer_state(),
        second_judge,
        requirement_id="req-go",
        target_topic="go.runtime",
        completed=True,
        targeted_claim_facts=["我使用 pprof 定位过线上 CPU 热点"],
    )
    final_plan = update_interview_plan(plan_after_followup, "req-go", score=4, completed=True)
    final_action = choose_after_answer_action(
        final_plan,
        final_state,
        _empty_answer_state(),
        second_judge,
        {"topic": "go.runtime", "target_requirement_id": "req-go", "followup_count": 1, "question_type": "theory"},
        [{"topic": "go.runtime", "target_requirement_id": "req-go", "followup_count": 1, "question_type": "theory"}],
        remaining_question_budget=0,
        max_followups=2,
        current_difficulty="medium",
    )
    assert final_action.selected_action == PlannerActionKind.FINISH_INTERVIEW.value

    round_data = {
        "sequence": 1,
        "status": "completed",
        "topic": "go.runtime",
        "target_requirement_id": "req-go",
        "score": 4,
        "next_difficulty": "medium",
        "followup_count": 1,
        "question_type": "theory",
        "planner_actions": [
            _asdict_action(question_action),
            _asdict_action(first_action),
            _asdict_action(final_action),
        ],
        "candidate_answers": [
            {"kind": "initial", "answer": "answer one", "evaluation": first_judge_data},
            {"kind": "followup", "answer": "answer two", "evaluation": second_judge_data},
        ],
        "answer_state": {
            "extractions": [
                {"answer_sequence": 1, "state": claim_state},
                {"answer_sequence": 2, "state": _empty_answer_state()},
            ]
        },
    }
    result = replay_session(_session_obj(plan, max_questions=1), [round_data])

    assert result["status"] == "deterministic"
    assert result["total_count"] == 3
    assert [item["decision_point"] for item in result["decisions"]] == [
        "question",
        "after_answer:1",
        "after_answer:2",
    ]
