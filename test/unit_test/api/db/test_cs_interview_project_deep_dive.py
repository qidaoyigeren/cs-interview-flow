"""Unit tests for the project deep-dive interview flow.

Covers the v2 resume extraction contract, the deterministic project attack map,
the project-aware planner, the project-fact follow-up mechanism, claim
verification state and the report matrix.  Everything here is pure domain logic
-- no LLM and no database -- except the explicit RAG refusals which use the
fake runtime.
"""

from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from api.apps.services.cs_interview.domain import (
    PROJECT_CLAIM_MAX_FOLLOWUPS,
    DomainError,
    JudgeResult,
    PlannerAction,
    PlannerActionKind,
    build_project_attack_map,
    choose_after_answer_action,
    choose_planner_action,
    initial_candidate_state,
    merge_candidate_state,
    update_interview_plan,
    validate_answer_state,
    validate_resume_extraction,
)
from api.apps.services.cs_interview.pipeline import generate_question
from api.apps.services.cs_interview.replay import replay_session

RESUME_TEXT = (
    "CS面试Agent项目：负责设计并实现基于RAGFlow的模拟面试系统，负责后端架构与RAG管线设计，"
    "采用Operation/Event/Checkpoint机制防止状态丢失，提升系统可靠性，QPS从100提升到500，"
    "通过A/B实验验证生成质量，使用Redis缓存减少数据库压力。"
    "交易网关项目：负责订单接口，采用异步消息解耦，防止重复扣款，优化数据库查询，"
    "将响应时间从200ms降低到80ms。"
)

CLAIMS = [
    {
        "claim_type": "mechanism",
        "text": "采用Operation/Event/Checkpoint机制防止状态丢失",
        "evidence_span": "采用Operation/Event/Checkpoint机制防止状态丢失",
        "topic_ids": ["ai.rag"],
        "skills": ["RAGFlow"],
        "risk_flags": [],
    },
    {
        "claim_type": "metric",
        "text": "QPS从100提升到500",
        "evidence_span": "QPS从100提升到500",
        "topic_ids": ["ai.evaluation"],
        "skills": [],
        "risk_flags": [],
    },
]

PAYLOAD = {
    "target_role": "ai_backend",
    "target_level": "senior",
    "technology_stack": ["RAGFlow", "Python", "Redis"],
    "claimed_skills": [
        {"skill": "RAG", "claimed_level": "proficient", "topics": ["ai.rag"]},
        {"skill": "Redis", "claimed_level": "experienced", "topics": ["backend.distributed"]},
    ],
    "projects": [
        {
            "name": "CS面试Agent",
            "role": "后端负责人",
            "summary": "基于RAGFlow的模拟面试系统，负责后端架构与RAG管线设计与实现。",
            "skills": ["RAGFlow", "Python", "Redis"],
            "claims": list(CLAIMS),
        },
        {
            "name": "交易网关",
            "role": "后端工程师",
            "summary": "负责订单接口与异步消息解耦，保证扣款一致性并优化查询性能。",
            "skills": ["Go", "Redis", "MySQL"],
            "claims": [
                {
                    "claim_type": "technology_choice",
                    "text": "采用异步消息解耦订单与支付",
                    "evidence_span": "采用异步消息解耦，防止重复扣款",
                    "topic_ids": ["backend.distributed"],
                    "skills": ["Redis"],
                    "risk_flags": [],
                }
            ],
        },
    ],
    "years_of_experience": 6,
    "summary": "AI 后端工程师，熟悉 RAG 与高并发服务。",
}


def _extraction() -> dict:
    return validate_resume_extraction(PAYLOAD, source_text=RESUME_TEXT)


def _job() -> dict:
    return {
        "requirements": [
            {
                "requirement_id": "req-rag",
                "text": "构建生产级 RAG 系统",
                "topic_ids": ["ai.rag"],
                "skills": ["RAG"],
                "category": "must_have",
                "weight": 0.5,
            },
            {
                "requirement_id": "req-dist",
                "text": "分布式与缓存",
                "topic_ids": ["backend.distributed"],
                "skills": ["Redis"],
                "category": "must_have",
                "weight": 0.5,
            },
        ]
    }


def _attack_map() -> list[dict]:
    return build_project_attack_map(_extraction(), _job(), {"target_role": "ai_backend"})


def _jd_plan_item(requirement_id="req-rag", topic_id="ai.rag", *, status="pending", attempt=0, must_have=True):
    return {
        "requirement_id": requirement_id,
        "topic_id": topic_id,
        "priority": 1.0,
        "objective": "验证 JD 要求",
        "preferred_question_type": "theory",
        "target_difficulty": "medium",
        "verification_strategy": "verify_resume_claim",
        "status": status,
        "attempt_count": attempt,
        "competency_id": topic_id,
        "must_have": must_have,
    }


def _judge(
    score=3,
    confidence=0.9,
    needs_followup=False,
    *,
    claim_verification="verified",
    technical_understanding=4,
) -> JudgeResult:
    return JudgeResult(
        score=score,
        verdict="excellent" if score >= 4 else "partial" if score >= 2 else "wrong_or_blank",
        covered_points=[],
        missing_points=[],
        factual_errors=[],
        needs_followup=needs_followup,
        followup_focus="boundary" if needs_followup else "",
        weak_point="",
        feedback="",
        evaluation_summary="",
        confidence=confidence,
        technical_understanding=technical_understanding,
        claim_verification=claim_verification,
    )


def _empty_answer_state() -> dict:
    return {
        "newly_claimed_facts": [],
        "project_facts": [],
        "contradictions": [],
        "covered_rubric_points": [],
        "unverified_boundaries": [],
        "deep_dive_branches": [],
    }


# --------------------------------------------------------------------------
# 1. Project claims may only be extracted from verbatim resume text
# --------------------------------------------------------------------------


def test_claim_evidence_span_must_be_contiguous_resume_text():
    forged = {
        **PAYLOAD,
        "projects": [
            {
                **PAYLOAD["projects"][0],
                "claims": [
                    {**CLAIMS[0], "evidence_span": "这段文字根本不在简历里，是模型编造的"},
                    {**CLAIMS[1]},
                ],
            }
        ],
    }
    validated = validate_resume_extraction(forged, source_text=RESUME_TEXT)
    claims = validated["projects"][0]["claims"]
    assert len(claims) == 1
    assert claims[0]["evidence_span"] in RESUME_TEXT


def test_claim_evidence_span_tolerates_punctuation_drift_but_stays_contiguous():
    drifted = {
        **PAYLOAD,
        "projects": [
            {
                **PAYLOAD["projects"][0],
                "claims": [
                    # Model dropped punctuation/whitespace: still mapped back to
                    # an exact contiguous slice of the resume.
                    {**CLAIMS[0], "evidence_span": "采用 Operation/Event/Checkpoint 机制防止状态丢失"},
                ],
            }
        ],
    }
    validated = validate_resume_extraction(drifted, source_text=RESUME_TEXT)
    span = validated["projects"][0]["claims"][0]["evidence_span"]
    assert span in RESUME_TEXT


def test_vague_performance_claims_are_flagged_as_risk():
    vague = {
        **PAYLOAD,
        "projects": [
            {
                **PAYLOAD["projects"][0],
                "claims": [
                    {
                        "claim_type": "metric",
                        "text": "大幅提升了系统性能，显著优化了响应速度",
                        "evidence_span": "提升系统可靠性",
                        "topic_ids": ["ai.rag"],
                        "skills": [],
                        "risk_flags": [],
                    }
                ],
            }
        ],
    }
    validated = validate_resume_extraction(vague, source_text=RESUME_TEXT)
    flags = validated["projects"][0]["claims"][0]["risk_flags"]
    assert "vague_metric" in flags


def test_deterministic_project_and_claim_ids():
    first = _extraction()
    second = validate_resume_extraction(PAYLOAD, source_text=RESUME_TEXT)
    project = first["projects"][0]
    assert project["project_id"].startswith("proj-")
    assert project["claims"][0]["claim_id"].startswith("clm-")
    assert project["project_id"] == second["projects"][0]["project_id"]
    assert project["claims"][0]["claim_id"] == second["projects"][0]["claims"][0]["claim_id"]


# --------------------------------------------------------------------------
# 2. Attack map is deterministic, ordered and replayable
# --------------------------------------------------------------------------


def test_attack_map_is_deterministic_and_ordered():
    first = _attack_map()
    second = build_project_attack_map(_extraction(), _job(), {"target_role": "ai_backend"})
    assert first == second
    priorities = [item["priority"] for item in first]
    assert priorities == sorted(priorities, reverse=True)
    assert all(item["status"] == "pending" and item["attempt_count"] == 0 for item in first)


def test_attack_map_covers_three_to_four_dimensions():
    amap = _attack_map()
    dimensions = {item["dimension"] for item in amap}
    assert 3 <= len(dimensions) <= 4
    # The main project (CS面试Agent) must dominate the map.
    main_project = _extraction()["projects"][0]["project_id"]
    assert all(item["project_id"] == main_project for item in amap)


def test_planner_decisions_are_replayable_given_the_same_inputs():
    amap = _attack_map()
    plan = [_jd_plan_item(status="verified", attempt=1)]
    state = initial_candidate_state(amap)
    kwargs = {"remaining_question_budget": 6, "current_difficulty": "medium"}
    first = choose_planner_action(list(plan), dict(state), [], **kwargs)
    second = choose_planner_action(list(plan), dict(state), [], **kwargs)
    assert first.target_project_id == second.target_project_id
    assert first.target_claim_id == second.target_claim_id
    assert first.project_dimension == second.project_dimension
    assert first.selected_action == second.selected_action


# --------------------------------------------------------------------------
# 3. High-priority project claims may lead; anchors are still never dropped
#    when the remaining budget only covers the protected must-have items
# --------------------------------------------------------------------------


def test_project_question_leads_even_with_unanchored_must_have():
    amap = _attack_map()
    plan = [_jd_plan_item("req-rag", "ai.rag", status="pending", attempt=0, must_have=True)]
    state = initial_candidate_state(amap)
    # The hard block ("no project question before every anchor is complete")
    # is removed: with budget slack, the JD-matched project claim leads.
    action = choose_planner_action(list(plan), state, [], remaining_question_budget=6, current_difficulty="medium")
    assert action.selected_action == PlannerActionKind.VERIFY_PROJECT_CLAIM.value
    assert action.target_project_id and action.target_claim_id and action.project_dimension
    assert action.question_kind == "adaptive"
    assert action.anchor_group_id == ""


def test_anchor_still_wins_when_budget_only_covers_protected_items():
    amap = _attack_map()
    plan = [_jd_plan_item("req-rag", "ai.rag", status="pending", attempt=0, must_have=True)]
    # Budget == number of protected/unattempted must-have items -> guard active,
    # so the anchor is reserved and project questions are excluded.
    action = choose_planner_action(list(plan), initial_candidate_state(amap), [], remaining_question_budget=1, current_difficulty="medium")
    assert action.selected_action != PlannerActionKind.VERIFY_PROJECT_CLAIM.value
    assert action.target_requirement_id == "req-rag"
    assert action.question_kind == "anchor"
    assert action.target_project_id == ""


def test_anchor_question_generation_ignores_project_personalization():
    # When the anchor IS selected (budget guard active), the anchor action must
    # never carry project targeting; the fixed reviewed question is used verbatim.
    amap = _attack_map()
    plan = [_jd_plan_item("req-rag", "ai.rag", status="pending", attempt=0, must_have=True)]
    action = choose_planner_action(list(plan), initial_candidate_state(amap), [], remaining_question_budget=1, current_difficulty="medium")
    assert action.target_project_id == ""
    assert action.target_claim_id == ""
    assert action.question_kind == "anchor"


def test_project_evidence_unavailable_target_is_skipped_by_the_planner():
    amap = _attack_map()
    target = amap[0]
    state = initial_candidate_state(amap)
    target_id = target["target_id"]
    state["project_claim_state"][target_id]["evidence_status"] = "unavailable"
    plan = [_jd_plan_item(status="verified", attempt=1)]
    action = choose_planner_action(list(plan), state, [], remaining_question_budget=3, current_difficulty="medium")
    # The unavailable target is skipped and the audit records the skip reason.
    eliminated = [(item.get("target_id"), item.get("reason")) for item in action.decision_audit.get("eliminated", [])]
    assert (target_id, "project_evidence_unavailable") in eliminated
    # A different (still available) target is pursued instead.
    assert action.selected_action == PlannerActionKind.VERIFY_PROJECT_CLAIM.value
    assert (action.target_project_id, action.target_claim_id, action.project_dimension) != (
        target["project_id"],
        target["claim_id"],
        target["dimension"],
    )


# --------------------------------------------------------------------------
# 4. After anchors complete, adaptive questions prefer project claims
# --------------------------------------------------------------------------


def test_project_question_wins_after_anchors_are_complete():
    amap = _attack_map()
    plan = [_jd_plan_item("req-rag", "ai.rag", status="pending", attempt=1, must_have=True)]
    # Anchor already done with high confidence on the same competency.
    rounds = [
        {
            "status": "completed",
            "competency_id": "ai.rag",
            "topic": "ai.rag",
            "question_kind": "anchor",
            "score": 3,
            "judge_confidence": 0.9,
            "evidence_evaluation": {},
        }
    ]
    action = choose_planner_action(list(plan), initial_candidate_state(amap), rounds, remaining_question_budget=6, current_difficulty="medium")
    assert action.selected_action == PlannerActionKind.VERIFY_PROJECT_CLAIM.value
    assert action.target_project_id and action.target_claim_id and action.project_dimension


def test_pending_project_claim_prevents_early_finish_after_all_jd_items_are_terminal():
    action = choose_planner_action(
        [_jd_plan_item(status="verified", attempt=1)],
        initial_candidate_state(_attack_map()),
        [],
        remaining_question_budget=3,
        current_difficulty="medium",
    )
    assert action.selected_action == PlannerActionKind.VERIFY_PROJECT_CLAIM.value
    assert action.target_project_id and action.target_claim_id


def test_project_foundation_mix_is_deterministic_and_auditable():
    amap = _attack_map()
    plan = [_jd_plan_item(status="pending", attempt=1, must_have=False)]
    first = choose_planner_action(plan, initial_candidate_state(amap), [], remaining_question_budget=6, current_difficulty="medium")
    assert first.selected_action == PlannerActionKind.VERIFY_PROJECT_CLAIM.value

    history = [
        {
            "question_kind": "adaptive",
            "topic": first.target_topic,
            "planner_actions": [asdict(first)],
        }
    ]
    second = choose_planner_action(plan, initial_candidate_state(amap), history, remaining_question_budget=5, current_difficulty="medium")
    assert second.target_project_id == ""
    assert second.decision_audit["budget"]["question_mix"] == {
        "project_questions": 1,
        "foundation_questions": 0,
        "counted_questions": 1,
        "project_share": 1.0,
        "target_project_share": 0.7,
        "next_preference": "foundation",
        "project_next_error": 0.3,
        "foundation_next_error": 0.2,
    }


# --------------------------------------------------------------------------
# 5. The same claim may be attacked at most twice, then switch dimension
# --------------------------------------------------------------------------


def test_same_claim_is_attacked_at_most_twice():
    amap = _attack_map()
    claim = amap[0]
    project_id, claim_id = claim["project_id"], claim["claim_id"]
    # Two attempts already consumed across the claim's dimensions.
    state = initial_candidate_state(amap)
    for target in amap:
        if target["project_id"] == project_id and target["claim_id"] == claim_id:
            target_id = target["target_id"]
            state["project_claim_state"][target_id]["attempt_count"] = 1
    plan = [_jd_plan_item(status="verified", attempt=1)]
    action = choose_planner_action(list(plan), state, [], remaining_question_budget=6, current_difficulty="medium")
    assert action.target_claim_id != claim_id or action.selected_action == PlannerActionKind.FINISH_INTERVIEW.value


def test_project_followup_stops_after_two_followups():
    amap = _attack_map()
    claim = amap[0]
    claim_id = claim["claim_id"]
    state = initial_candidate_state(amap)
    round_data = {
        "topic": "ai.rag",
        "competency_id": "ai.rag",
        "target_requirement_id": "req-rag",
        "question_type": "scenario",
        "followup_count": PROJECT_CLAIM_MAX_FOLLOWUPS,
        "planner_actions": [
            {
                "selected_action": "verify_project_claim",
                "target_project_id": claim["project_id"],
                "target_claim_id": claim_id,
                "project_dimension": claim["dimension"],
                "project_followup_depth": PROJECT_CLAIM_MAX_FOLLOWUPS,
                "supporting_state": {"target_claim_fact": claim["claim_text"]},
            }
        ],
    }
    answer_state = {
        **_empty_answer_state(),
        "project_facts": [
            {
                "fact": "新增的重试机制",
                "fact_kind": "mechanism",
                "project_id": claim["project_id"],
                "claim_id": claim_id,
                "topic_ids": ["ai.rag"],
                "evidence_span": "新增的重试机制",
            }
        ],
    }
    action = choose_after_answer_action(
        [_jd_plan_item("req-rag", "ai.rag", status="pending")],
        state,
        answer_state,
        _judge(3, needs_followup=True),
        round_data,
        [],
        remaining_question_budget=5,
        max_followups=2,
        current_difficulty="medium",
    )
    assert action.selected_action != PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value or action.target_claim_id != claim_id


# --------------------------------------------------------------------------
# 6. project_facts directly trigger the next deep-dive follow-up
# --------------------------------------------------------------------------


def test_project_facts_trigger_a_project_followup():
    amap = _attack_map()
    claim = amap[0]
    claim_id = claim["claim_id"]
    state = initial_candidate_state(amap)
    round_data = {
        "topic": "ai.rag",
        "competency_id": "ai.rag",
        "target_requirement_id": "req-rag",
        "question_type": "scenario",
        "followup_count": 0,
        "planner_actions": [
            {
                "selected_action": "verify_project_claim",
                "target_project_id": claim["project_id"],
                "target_claim_id": claim_id,
                "project_dimension": claim["dimension"],
                "project_followup_depth": 0,
                "supporting_state": {"target_claim_fact": claim["claim_text"]},
            }
        ],
    }
    answer_state = {
        **_empty_answer_state(),
        "project_facts": [
            {
                "fact": "Worker 崩溃后通过 Checkpoint 重放恢复",
                "fact_kind": "failure_mode",
                "project_id": claim["project_id"],
                "claim_id": claim_id,
                "topic_ids": ["ai.rag"],
                "evidence_span": "Worker 崩溃后通过 Checkpoint 重放恢复",
            }
        ],
    }
    action = choose_after_answer_action(
        [_jd_plan_item("req-rag", "ai.rag", status="pending")],
        state,
        answer_state,
        _judge(3),
        round_data,
        [],
        remaining_question_budget=5,
        max_followups=2,
        current_difficulty="medium",
    )
    assert action.selected_action == PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value
    assert action.target_project_id == claim["project_id"]
    assert action.target_claim_id == claim_id
    assert action.project_followup_depth == 1


def test_project_evidence_and_attempts_accumulate_across_followups():
    target = _attack_map()[0]
    project_target = {
        "project_id": target["project_id"],
        "claim_id": target["claim_id"],
        "dimension": target["dimension"],
        "claim_text": target["claim_text"],
        "question_id": "q-project",
    }
    first_answer = {
        **_empty_answer_state(),
        "project_facts": [
            {
                "fact": "Checkpoint 会从最后一个已提交事件继续重放",
                "fact_kind": "mechanism",
                "project_id": target["project_id"],
                "claim_id": target["claim_id"],
                "topic_ids": [target["topic_id"]],
                "evidence_span": "Checkpoint 从最后一个已提交事件继续重放",
            }
        ],
    }
    state = merge_candidate_state(
        initial_candidate_state(_attack_map()),
        first_answer,
        _judge(3, confidence=0.9),
        requirement_id="req-rag",
        target_topic=target["topic_id"],
        completed=False,
        project_target=project_target,
    )
    target_id = target["target_id"]
    assert state["project_claim_state"][target_id]["attempt_count"] == 1
    assert len(state["project_claim_state"][target_id]["answered_evidence"]) == 1
    assert state["project_claim_state"][target_id]["status"] == "partial"

    state = merge_candidate_state(
        state,
        _empty_answer_state(),
        _judge(4, confidence=0.95),
        requirement_id="req-rag",
        target_topic=target["topic_id"],
        completed=True,
        project_target=project_target,
    )
    assert state["project_claim_state"][target_id]["attempt_count"] == 2
    assert len(state["project_claim_state"][target_id]["answered_evidence"]) == 1
    assert state["project_claim_state"][target_id]["status"] == "verified"


def test_project_contradiction_followup_keeps_exact_project_target():
    target = _attack_map()[0]
    round_data = {
        "topic": target["topic_id"],
        "competency_id": target["topic_id"],
        "target_requirement_id": "req-rag",
        "question_type": "scenario",
        "followup_count": 0,
        "planner_actions": [
            {
                "selected_action": "verify_project_claim",
                "target_project_id": target["project_id"],
                "target_claim_id": target["claim_id"],
                "project_dimension": target["dimension"],
                "project_followup_depth": 0,
            }
        ],
    }
    answer_state = {
        **_empty_answer_state(),
        "contradictions": [
            {
                "contradiction_id": "contra-project",
                "statement": "任务可以从断点恢复",
                "conflicts_with": target["claim_text"],
                "topic_ids": [target["topic_id"]],
                "status": "unresolved",
            }
        ],
    }
    action = choose_after_answer_action(
        [_jd_plan_item(status="partial", attempt=1)],
        initial_candidate_state(_attack_map()),
        answer_state,
        _judge(2),
        round_data,
        [],
        remaining_question_budget=3,
        max_followups=2,
        current_difficulty="medium",
    )
    assert action.selected_action == PlannerActionKind.RESOLVE_CONTRADICTION.value
    assert action.target_project_id == target["project_id"]
    assert action.target_claim_id == target["claim_id"]
    assert action.project_dimension == target["dimension"]


# --------------------------------------------------------------------------
# 7. Facts from different projects never chain together
# --------------------------------------------------------------------------


def test_project_facts_never_cross_projects():
    extraction = _extraction()
    project_a = extraction["projects"][0]
    project_b = extraction["projects"][1]
    claim_a = project_a["claims"][0]["claim_id"]
    # A fact attributed to project A but referencing project B's claim loses its
    # ownership and cannot drive a follow-up.
    known = {claim_a: project_a["project_id"]}
    validated = validate_answer_state(
        {
            "project_facts": [
                {
                    "fact": "异步解耦",
                    "fact_kind": "mechanism",
                    "project_id": project_a["project_id"],
                    "claim_id": project_b["claims"][0]["claim_id"],
                    "evidence_span": "异步解耦",
                }
            ],
            "contradictions": [],
        },
        "异步解耦",
        known_project_claims=known,
    )
    assert validated["project_facts"][0]["project_id"] == ""
    assert validated["project_facts"][0]["claim_id"] == ""


def test_project_facts_are_not_merged_into_ordinary_new_claims():
    amap = _attack_map()
    state = initial_candidate_state(amap)
    answer_state = {
        **_empty_answer_state(),
        "project_facts": [
            {
                "fact": "缓存击穿处理",
                "fact_kind": "mechanism",
                "project_id": amap[0]["project_id"],
                "claim_id": amap[0]["claim_id"],
                "topic_ids": ["ai.rag"],
                "evidence_span": "缓存击穿处理",
            }
        ],
    }
    merged = merge_candidate_state(state, answer_state, _judge(3), requirement_id="req-rag", target_topic="ai.rag", completed=True, required_score=3, project_target=None)
    assert len(merged["project_facts"]) == 1
    assert merged["newly_claimed_facts"] == []


# --------------------------------------------------------------------------
# 8. Vague metrics trigger metric verification
# --------------------------------------------------------------------------


def test_vague_metric_claim_gets_a_metric_dimension_target():
    extraction = _extraction()
    amap = build_project_attack_map(extraction, _job(), {"target_role": "ai_backend"})
    metric_claim = next(c for c in extraction["projects"][0]["claims"] if c["claim_type"] == "metric")
    targets = [t for t in amap if t["claim_id"] == metric_claim["claim_id"]]
    assert any(t["dimension"] == "metric" for t in targets)


# --------------------------------------------------------------------------
# 9. Technology choices trigger an alternatives challenge
# --------------------------------------------------------------------------


def test_technology_choice_triggers_selection_and_tradeoff_dimensions():
    technology_project = {**PAYLOAD, "projects": [PAYLOAD["projects"][1]]}
    extraction = validate_resume_extraction(technology_project, source_text=RESUME_TEXT)
    amap = build_project_attack_map(extraction, _job(), {"target_role": "ai_backend"})
    choice_claim = extraction["projects"][0]["claims"][0]["claim_id"]
    dimensions = {t["dimension"] for t in amap if t["claim_id"] == choice_claim}
    assert "selection" in dimensions
    assert "tradeoff" in dimensions


# --------------------------------------------------------------------------
# 10. Happy-path-only descriptions trigger failure-boundary probes
# --------------------------------------------------------------------------


def test_happy_path_claim_triggers_failure_dimension():
    happy = {
        **PAYLOAD,
        "projects": [
            {
                **PAYLOAD["projects"][0],
                "claims": [
                    {
                        "claim_type": "mechanism",
                        "text": "实现了核心下单流程并上线运行",
                        "evidence_span": "负责订单接口",
                        "topic_ids": ["backend.distributed"],
                        "skills": [],
                        "risk_flags": [],
                    }
                ],
            }
        ],
    }
    extraction = validate_resume_extraction(happy, source_text=RESUME_TEXT)
    flags = extraction["projects"][0]["claims"][0]["risk_flags"]
    assert "happy_path_only" in flags
    amap = build_project_attack_map(extraction, _job(), {"target_role": "ai_backend"})
    assert any(t["dimension"] == "failure" for t in amap)


# --------------------------------------------------------------------------
# 11. A new project claim can never be verified in the same round
# --------------------------------------------------------------------------


def test_new_project_claim_cannot_be_verified_in_the_same_round():
    amap = _attack_map()
    state = initial_candidate_state(amap)
    # The answer introduces a brand-new fact attributed to a claim that exists
    # in the attack map.  It lands in project_facts as pending only.
    answer_state = {
        **_empty_answer_state(),
        "project_facts": [
            {
                "fact": "新的限流机制",
                "fact_kind": "mechanism",
                "project_id": amap[0]["project_id"],
                "claim_id": amap[0]["claim_id"],
                "topic_ids": ["ai.rag"],
                "evidence_span": "新的限流机制",
            }
        ],
    }
    merged = merge_candidate_state(
        state,
        answer_state,
        _judge(4, confidence=0.95),
        requirement_id="req-rag",
        target_topic="ai.rag",
        completed=True,
        required_score=3,
        project_target=None,
    )
    assert "status" not in merged["project_facts"][0]
    # Nothing in the attack map was verified because no target was pursued.
    assert all(row["status"] == "untested" for row in merged["project_claim_state"].values())


# --------------------------------------------------------------------------
# 12. No RAG evidence -> refuse to generate a project question
# --------------------------------------------------------------------------


def test_project_question_is_refused_without_verified_evidence():
    from test.unit_test.api.db.test_cs_interview_pipeline import CONFIG, PROFILE, FakeRuntime

    amap = _attack_map()
    target = amap[0]
    action = PlannerAction(
        PlannerActionKind.VERIFY_PROJECT_CLAIM.value,
        None,
        target["topic_id"],
        "验证项目声明",
        {"target_claim_fact": target["claim_text"], "target_project_id": target["project_id"], "target_claim_id": target["claim_id"]},
        target_difficulty="medium",
        preferred_question_type="scenario",
        question_kind="adaptive",
        competency_id=target["topic_id"],
        target_project_id=target["project_id"],
        target_claim_id=target["claim_id"],
        project_dimension=target["dimension"],
        action_factors={"claim_text": target["claim_text"], "claim_type": target["claim_type"]},
    )
    runtime = FakeRuntime()  # no evidence at all
    resume_context = _extraction()
    with pytest.raises(DomainError) as error:
        asyncio_run(
            generate_question(
                runtime,
                "tenant-1",
                PROFILE,
                CONFIG,
                [],
                action,
                resume_context=resume_context,
                job_context=_job(),
            )
        )
    # A project target without claim-relevant evidence must signal
    # project_evidence_irrelevant (the service downgrades it to a foundation
    # question) rather than the generic insufficient_evidence that fails the
    # whole session.
    assert error.value.code == "project_evidence_irrelevant"


# --------------------------------------------------------------------------
# 13. Replay reproduces the exact project claim state
# --------------------------------------------------------------------------


def test_replay_reproduces_project_claim_state():
    amap = _attack_map()
    claim = amap[0]
    claim_id = claim["claim_id"]
    target = {
        "project_id": claim["project_id"],
        "claim_id": claim_id,
        "dimension": claim["dimension"],
        "claim_text": claim["claim_text"],
        "followup_depth": 0,
        "question_id": "q1",
    }
    answer_state = {
        **_empty_answer_state(),
        "project_facts": [
            {
                "fact": "Checkpoint 重放恢复",
                "fact_kind": "mechanism",
                "project_id": claim["project_id"],
                "claim_id": claim_id,
                "topic_ids": ["ai.rag"],
                "evidence_span": "Checkpoint 重放恢复",
            }
        ],
    }
    live = merge_candidate_state(
        initial_candidate_state(amap),
        answer_state,
        _judge(4, confidence=0.95),
        requirement_id="req-rag",
        target_topic="ai.rag",
        completed=True,
        required_score=3,
        project_target=target,
    )
    plan = [_jd_plan_item(status="verified", attempt=1)]
    question_action = choose_planner_action(
        plan,
        initial_candidate_state(amap),
        [],
        remaining_question_budget=1,
        current_difficulty="medium",
    )
    final_plan = update_interview_plan(plan, question_action.target_requirement_id, score=4, completed=True)
    final_action = choose_after_answer_action(
        final_plan,
        live,
        answer_state,
        _judge(4, confidence=0.95),
        {
            "topic": question_action.target_topic,
            "competency_id": question_action.competency_id,
            "target_requirement_id": question_action.target_requirement_id,
            "question_type": question_action.preferred_question_type,
            "followup_count": 0,
            "planner_actions": [asdict(question_action)],
        },
        [],
        remaining_question_budget=0,
        max_followups=0,
        current_difficulty="medium",
    )
    session = SimpleNamespace(
        id="project-replay",
        tenant_id="tenant-1",
        planner_version=question_action.planner_version,
        profile_snapshot={"initial_difficulty": "medium"},
        competency_snapshot={},
        initial_interview_plan=plan,
        initial_candidate_state=initial_candidate_state(amap),
        max_questions=1,
        max_followups=0,
    )
    round_data = {
        "sequence": 1,
        "status": "completed",
        "question_id": "q1",
        "topic": question_action.target_topic,
        "competency_id": question_action.competency_id,
        "question_kind": question_action.question_kind,
        "target_requirement_id": question_action.target_requirement_id,
        "question_type": question_action.preferred_question_type,
        "followup_count": 0,
        "score": 4,
        "next_difficulty": "medium",
        "planner_actions": [asdict(question_action), asdict(final_action)],
        "candidate_answers": [{"kind": "initial", "answer": "answer", "evaluation": asdict(_judge(4, confidence=0.95))}],
        "answer_state": {"extractions": [{"answer_sequence": 1, "state": answer_state}]},
    }
    replay = replay_session(session, [round_data])
    assert replay["status"] == "deterministic"
    assert replay["final_project_claim_state"] == live["project_claim_state"]
    target_id = target["project_id"] + "::" + claim_id + "::" + claim["dimension"]
    assert live["project_claim_state"][target_id]["status"] == "verified"
    assert live["project_claim_state"][target_id]["attempt_count"] == 1


# --------------------------------------------------------------------------
# Report matrix separates technical score from claim truthfulness
# --------------------------------------------------------------------------


def test_report_matrix_separates_technical_score_from_claim_truthfulness():
    from api.apps.services.cs_interview.domain import build_report

    amap = _attack_map()
    claim = amap[0]
    target = {
        "project_id": claim["project_id"],
        "claim_id": claim["claim_id"],
        "dimension": claim["dimension"],
        "claim_text": claim["claim_text"],
        "followup_depth": 0,
        "question_id": "q1",
    }
    answer_state = {
        **_empty_answer_state(),
        "project_facts": [
            {
                "fact": "Checkpoint 重放恢复",
                "fact_kind": "mechanism",
                "project_id": claim["project_id"],
                "claim_id": claim["claim_id"],
                "topic_ids": ["ai.rag"],
                "evidence_span": "Checkpoint 重放恢复",
            }
        ],
    }
    state = merge_candidate_state(
        initial_candidate_state(amap),
        answer_state,
        _judge(4, confidence=0.95),
        requirement_id="req-rag",
        target_topic="ai.rag",
        completed=True,
        required_score=3,
        project_target=target,
    )
    round_row = {
        "status": "completed",
        "score": 4,
        "initial_score": 4,
        "followup_count": 0,
        "topic": "ai.rag",
        "difficulty": "medium",
        "category": "interview_experience",
        "competency_id": "ai.rag",
        "question_id": "q1",
        "question_kind": "adaptive",
        "judge_confidence": 0.95,
        "evidence_evaluation": {},
        "planner_actions": [
            {
                "target_project_id": claim["project_id"],
                "target_claim_id": claim["claim_id"],
            }
        ],
    }
    report = build_report(
        [round_row],
        {"target_role": "ai_backend", "initial_difficulty": "medium"},
        resume_snapshot=_extraction(),
        candidate_state=state,
    )
    matrix = report["project_claim_verification"]
    entry = next(item for item in matrix if item["claim_id"] == claim["claim_id"])
    assert entry["verification_status"] == "verified"
    assert entry["score"] == 4.0
    # The untested metric claim stays untested even though the candidate scored
    # well on a related topic.
    metric_claim = _extraction()["projects"][0]["claims"][1]["claim_id"]
    metric_entry = next(item for item in matrix if item["claim_id"] == metric_claim)
    assert metric_entry["verification_status"] == "untested"


def _asyncio_run(coro):
    import asyncio

    try:
        return asyncio.get_event_loop().run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


asyncio_run = _asyncio_run
