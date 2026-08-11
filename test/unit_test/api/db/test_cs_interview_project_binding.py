"""Unit tests for the project deep-dive question binding chain.

Covers the deterministic ProjectQuestionContract gate, claim-level evidence
validation, claim-specific rubric generation, the claim-verification state gate
(generic principle answers can never mark a claim ``verified``), the same-claim
follow-up budget and the foundation/project frontend classification.  These are
the regression tests for "把 Go Context/GMP 等通用八股题伪装成项目深挖题".

Everything here is pure domain/pipeline logic -- no LLM and no database --
except the explicit RAG-evidence scenarios which use the fake runtime.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from api.apps.services.cs_interview.domain import (
    PROJECT_CLAIM_MAX_FOLLOWUPS,
    DomainError,
    JudgeResult,
    PlannerAction,
    PlannerActionKind,
    PolicyDecision,
    ProjectQuestionContract,
    build_project_attack_map,
    build_project_question_contract,
    choose_after_answer_action,
    choose_planner_action,
    concept_terms,
    downgrade_project_action,
    initial_candidate_state,
    merge_candidate_state,
    question_category_for_round,
    validate_project_evidence,
    validate_project_question_contract,
    validate_resume_extraction,
)
from api.apps.services.cs_interview.pipeline import (
    generate_followup,
    generate_question,
    validate_question_grounding,
)
from api.apps.services.cs_interview.judge import _project_contract_context
from api.apps.services.cs_interview.reliability import classify_failure

RESUME_TEXT = (
    "GoTalk项目：面向即时通讯的可靠消息系统，负责投递链路与性能优化，后端负责人。"
    "通过 Redis Lua 租约、ACK Deadline 和 Kafka 实现可靠投递。"
    "通过 CityHash 分桶和 Buffer Pool 将 GC 次数从 192 次降低至 3 次。"
)

PAYLOAD = {
    "target_role": "go_backend",
    "target_level": "senior",
    "technology_stack": ["Go", "Redis", "Kafka"],
    "claimed_skills": [
        {"skill": "Go", "claimed_level": "proficient", "topics": ["go.runtime"]},
        {"skill": "Redis", "claimed_level": "experienced", "topics": ["backend.distributed"]},
    ],
    "projects": [
        {
            "name": "GoTalk",
            "role": "后端负责人",
            "summary": "面向即时通讯的可靠消息系统，负责投递链路与性能优化。",
            "skills": ["Go", "Redis", "Kafka"],
            "claims": [
                {
                    "claim_type": "reliability",
                    "text": "通过 Redis Lua 租约、ACK Deadline 和 Kafka 实现可靠投递",
                    "evidence_span": "通过 Redis Lua 租约、ACK Deadline 和 Kafka 实现可靠投递",
                    "topic_ids": ["backend.distributed"],
                    "skills": ["Redis", "Kafka"],
                    "risk_flags": ["happy_path_only"],
                },
                {
                    "claim_type": "metric",
                    "text": "通过 CityHash 分桶和 Buffer Pool 将 GC 次数从 192 次降低至 3 次",
                    "evidence_span": "通过 CityHash 分桶和 Buffer Pool 将 GC 次数从 192 次降低至 3 次",
                    "topic_ids": ["go.runtime"],
                    "skills": ["Go"],
                    "risk_flags": [],
                },
            ],
        }
    ],
    "years_of_experience": 6,
    "summary": "Go 后端工程师，熟悉高并发与可靠投递。",
}


def _extraction():
    return validate_resume_extraction(PAYLOAD, source_text=RESUME_TEXT)


def _job():
    return {
        "requirements": [
            {
                "requirement_id": "req-dist",
                "text": "分布式与消息可靠投递",
                "topic_ids": ["backend.distributed"],
                "skills": ["Kafka"],
                "category": "must_have",
                "weight": 0.5,
            },
            {
                "requirement_id": "req-go",
                "text": "Go 高并发编程",
                "topic_ids": ["go.runtime"],
                "skills": ["Go"],
                "category": "must_have",
                "weight": 0.5,
            },
        ]
    }


def _attack_map():
    return build_project_attack_map(_extraction(), _job(), {"target_role": "go_backend"})


def _reliability_claim():
    return next(claim for claim in _extraction()["projects"][0]["claims"] if claim["claim_type"] == "reliability")


def _metric_claim():
    return next(claim for claim in _extraction()["projects"][0]["claims"] if claim["claim_type"] == "metric")


def _jd_item(requirement_id="req-dist", topic_id="backend.distributed", *, status="pending", attempt=0, must_have=True):
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
    missing_points=(),
    *,
    claim_verification="verified",
    technical_understanding=4,
):
    return JudgeResult(
        score=score,
        verdict="excellent" if score >= 4 else "partial" if score >= 2 else "wrong_or_blank",
        covered_points=[],
        missing_points=list(missing_points),
        factual_errors=[],
        needs_followup=False,
        followup_focus="",
        weak_point="",
        feedback="",
        evaluation_summary="",
        confidence=confidence,
        technical_understanding=technical_understanding,
        claim_verification=claim_verification,
    )


def _empty_answer_state():
    return {"newly_claimed_facts": [], "project_facts": [], "contradictions": []}


def _contract(claim, dimension="failure", evidence=()):
    return build_project_question_contract(_extraction()["projects"][0], claim, dimension, list(evidence))


def _claim_relevant_evidence(question_id="chunk-reliable"):
    return {
        "evidence_id": "chunk-ok",
        "dataset_id": "experience-ds",
        "document_id": "doc-1",
        "document_name": "reliable delivery notes",
        "content": (
            "消息写入 Kafka 后 Worker 持有 Redis Lua 租约，ACK Deadline 到达前提交 ACK；"
            "Worker 恢复后通过租约去重避免重复消息被客户端感知。"
        ),
        "metadata": {
            "content_type": "interview_experience",
            "role": "go_backend",
            "topic": "backend.distributed",
            "difficulty": "medium",
            "question_id": question_id,
            "source": "synthetic-fixture",
            "source_date": "2026-01-01",
            "quality_score": 0.9,
            "verified": True,
            "license": "CC0",
        },
    }


def _context_evidence():
    return {
        "evidence_id": "chunk-ctx",
        "dataset_id": "experience-ds",
        "document_id": "doc-2",
        "document_name": "go context notes",
        "content": "Go context.Context 的取消传播和 deadline。父 context 取消会传播给派生子 context。",
        "metadata": {
            "content_type": "interview_experience",
            "role": "go_backend",
            "topic": "backend.distributed",
            "difficulty": "medium",
            "question_id": "chunk-ctx-q",
            "source": "synthetic-fixture",
            "source_date": "2026-01-01",
            "quality_score": 0.9,
            "verified": True,
            "license": "CC0",
        },
    }


def _project_action(claim, dimension="failure"):
    proj = _extraction()["projects"][0]
    return PlannerAction(
        PlannerActionKind.VERIFY_PROJECT_CLAIM.value,
        "req-dist",
        "backend.distributed",
        "验证项目声明",
        {"target_claim_fact": claim["text"], "project_name": proj["name"], "claim_type": claim["claim_type"]},
        target_difficulty="medium",
        preferred_question_type="scenario",
        question_kind="adaptive",
        competency_id="backend.distributed",
        target_project_id=proj["project_id"],
        target_claim_id=claim["claim_id"],
        project_dimension=dimension,
        action_factors={"claim_text": claim["text"], "claim_type": claim["claim_type"]},
    )


# --------------------------------------------------------------------------
# 1. A GoTalk reliability claim cannot generate an unrelated Context question
# --------------------------------------------------------------------------


def test_reliability_claim_rejects_unrelated_context_question():
    claim = _reliability_claim()
    contract = _contract(claim, "failure", [_claim_relevant_evidence()])
    evidence = [_claim_relevant_evidence()]
    decision = PolicyDecision("backend.distributed", "backend.distributed", "interview_experience", "scenario", "medium", False, ())
    action = _project_action(claim)
    requirement = _job()["requirements"][0]
    bad = "解释 Go context.Context 的取消传播和 deadline"
    with pytest.raises(DomainError) as error:
        validate_question_grounding(
            bad,
            "参考",
            ["点"],
            decision,
            evidence,
            reused_reviewed_material=False,
            requirement=requirement,
            planner_action=action,
            project_contract=contract,
        )
    assert error.value.code in {"project_question_unbound", "ungrounded_question"}

    good = (
        "你在 GoTalk 中通过 Redis Lua 租约、ACK Deadline 和 Kafka 保证可靠投递。"
        "假设 Worker 已写入 Kafka，但在提交 ACK 前宕机，恢复后如何避免重复消息被客户端感知？"
    )
    validation = validate_question_grounding(
        good,
        "Worker 持有 Redis Lua 租约，ACK 提交后释放；崩溃后根据租约去重避免重复消息。",
        ["租约", "ACK", "去重"],
        decision,
        evidence,
        reused_reviewed_material=False,
        requirement=requirement,
        planner_action=action,
        project_contract=contract,
    )
    assert validation["project_bound"] is True
    assert len(validation["claim_binding_terms"]) >= 2


def test_project_name_prefix_cannot_disguise_an_unrelated_question():
    claim = _reliability_claim()
    contract = _contract(claim, "failure", [_claim_relevant_evidence()])
    decision = PolicyDecision("backend.distributed", "backend.distributed", "interview_experience", "scenario", "medium", False, ())
    with pytest.raises(DomainError) as error:
        validate_question_grounding(
            "你在 GoTalk 项目中如何理解 context.Context 的 deadline 和取消传播？",
            "Redis Lua 租约、ACK Deadline 与 Kafka 共同处理可靠投递的故障窗口。",
            ["租约", "ACK", "故障恢复"],
            decision,
            [_claim_relevant_evidence()],
            reused_reviewed_material=False,
            requirement=_job()["requirements"][0],
            planner_action=_project_action(claim),
            project_contract=contract,
        )
    assert error.value.code in {"project_question_unbound", "ungrounded_question"}


def test_project_question_must_attack_the_selected_dimension():
    claim = _reliability_claim()
    contract = _contract(claim, "failure", [_claim_relevant_evidence()])
    decision = PolicyDecision("backend.distributed", "backend.distributed", "interview_experience", "scenario", "medium", False, ())
    with pytest.raises(DomainError) as error:
        validate_question_grounding(
            "你在 GoTalk 中为什么选择 Redis Lua 租约和 Kafka，而不是其他消息方案？",
            "Redis Lua 租约与 Kafka 的可靠投递需要结合项目约束说明。",
            ["租约", "Kafka", "项目约束"],
            decision,
            [_claim_relevant_evidence()],
            reused_reviewed_material=False,
            requirement=_job()["requirements"][0],
            planner_action=_project_action(claim),
            project_contract=contract,
        )
    assert error.value.code == "project_question_dimension_mismatch"


# --------------------------------------------------------------------------
# 2. A project question requires a complete project_id/claim_id/dimension
# --------------------------------------------------------------------------


def test_project_question_requires_a_complete_contract():
    contract = _contract(_reliability_claim(), "failure", [_claim_relevant_evidence()])
    validated = validate_project_question_contract(contract)
    assert validated["valid"] is True
    assert validated["rubric_point_count"] >= 3

    incomplete = ProjectQuestionContract(
        project_id="",
        project_name="GoTalk",
        claim_id="clm-x",
        claim_text="文本",
        claim_type="mechanism",
        project_dimension="",
        core_concepts=("x",),
        evidence_chunk_ids=("e1",),
        inspected_mechanism="机制",
        claim_specific_rubric=(),
    )
    with pytest.raises(DomainError) as error:
        validate_project_question_contract(incomplete)
    assert error.value.code == "invalid_project_contract"


def test_contract_without_claim_relevant_evidence_cannot_be_used_for_a_question():
    # Evidence is filled after retrieval; a contract without evidence must fail
    # the evidence_required gate so no project question can be generated.
    contract = _contract(_reliability_claim(), "failure", [])
    with pytest.raises(DomainError) as error:
        validate_project_question_contract(contract)
    assert error.value.code == "invalid_project_contract"
    assert "evidence_chunk_ids" in error.value.message


# --------------------------------------------------------------------------
# 3. The question contract carries the project scenario + claim mechanism
# --------------------------------------------------------------------------


def test_contract_extracts_the_claim_mechanism_and_core_concepts():
    claim = _reliability_claim()
    contract = _contract(claim, "failure")
    assert contract.inspected_mechanism == "Redis Lua 租约、ACK Deadline 和 Kafka"
    assert {"redis", "lua", "kafka"} <= set(contract.core_concepts)
    # Generic words such as "context"/"deadline" can never bind a question to
    # this claim by themselves; they are excluded from the distinctive set.
    from api.apps.services.cs_interview.domain import claim_binding_terms

    binding = claim_binding_terms(claim["text"])
    assert "context" not in binding
    assert "lua" in binding and "kafka" in binding


def test_contract_binds_the_retrieved_evidence_chunks():
    evidence = [_claim_relevant_evidence()]
    contract = _contract(_reliability_claim(), "failure", evidence)
    assert tuple(contract.evidence_chunk_ids) == ("chunk-ok",)


# --------------------------------------------------------------------------
# 4. Only claim-specific implementation detail can mark the claim verified
# --------------------------------------------------------------------------


def test_generic_kafka_redis_principle_answer_cannot_verify_the_claim():
    claim = _reliability_claim()
    amap = _attack_map()
    target = next(item for item in amap if item["claim_id"] == claim["claim_id"])
    state = initial_candidate_state(amap)
    project_target = {
        "project_id": target["project_id"],
        "claim_id": target["claim_id"],
        "dimension": target["dimension"],
        "claim_text": target["claim_text"],
        "question_id": "q1",
    }
    generic_fact = {
        "fact": "Kafka 通过分区顺序和消费组保证消息，Redis 缓存降低延迟",
        "fact_kind": "mechanism",
        "project_id": target["project_id"],
        "claim_id": target["claim_id"],
        "evidence_span": "Kafka 分区顺序",
    }
    merged = merge_candidate_state(
        state,
        {**_empty_answer_state(), "project_facts": [generic_fact]},
        _judge(4, confidence=0.95, claim_verification="unverified"),
        requirement_id="req-dist",
        target_topic="backend.distributed",
        completed=True,
        project_target=project_target,
    )
    target_id = target["target_id"]
    assert merged["project_claim_state"][target_id]["status"] == "partial"


def test_claim_specific_implementation_answer_verifies_the_claim():
    claim = _reliability_claim()
    amap = _attack_map()
    target = next(item for item in amap if item["claim_id"] == claim["claim_id"])
    state = initial_candidate_state(amap)
    project_target = {
        "project_id": target["project_id"],
        "claim_id": target["claim_id"],
        "dimension": target["dimension"],
        "claim_text": target["claim_text"],
        "question_id": "q2",
    }
    specific_fact = {
        "fact": "我在 GoTalk 里用 Redis Lua 租约保序，Worker 崩溃后 ACK 超时释放租约重新投递",
        "fact_kind": "failure_mode",
        "project_id": target["project_id"],
        "claim_id": target["claim_id"],
        "evidence_span": "lua租约 ACK",
    }
    merged = merge_candidate_state(
        state,
        {**_empty_answer_state(), "project_facts": [specific_fact]},
        _judge(4, confidence=0.95),
        requirement_id="req-dist",
        target_topic="backend.distributed",
        completed=True,
        project_target=project_target,
    )
    assert merged["project_claim_state"][target["target_id"]]["status"] == "verified"


def test_llm_fact_summary_cannot_replace_an_exact_claim_specific_answer_span():
    claim = _reliability_claim()
    amap = _attack_map()
    target = next(item for item in amap if item["claim_id"] == claim["claim_id"])
    project_target = {
        "project_id": target["project_id"],
        "claim_id": target["claim_id"],
        "dimension": target["dimension"],
        "claim_text": target["claim_text"],
    }
    hallucinated_summary = {
        "fact": "我使用 Redis Lua 租约和 ACK Deadline 处理可靠投递",
        "fact_kind": "mechanism",
        "project_id": target["project_id"],
        "claim_id": target["claim_id"],
        "evidence_span": "我就是按常见方式做的",
    }
    merged = merge_candidate_state(
        initial_candidate_state(amap),
        {**_empty_answer_state(), "project_facts": [hallucinated_summary]},
        _judge(4, confidence=0.95),
        requirement_id="req-dist",
        target_topic="backend.distributed",
        completed=True,
        project_target=project_target,
    )
    assert merged["project_claim_state"][target["target_id"]]["status"] == "partial"


def test_specific_answer_evidence_still_requires_claim_verification_verdict():
    claim = _reliability_claim()
    amap = _attack_map()
    target = next(item for item in amap if item["claim_id"] == claim["claim_id"])
    specific_fact = {
        "fact": "Redis Lua 租约和 ACK Deadline 的故障恢复",
        "fact_kind": "failure_mode",
        "project_id": target["project_id"],
        "claim_id": target["claim_id"],
        "evidence_span": "Redis Lua 租约和 ACK Deadline 的故障恢复",
    }
    merged = merge_candidate_state(
        initial_candidate_state(amap),
        {**_empty_answer_state(), "project_facts": [specific_fact]},
        _judge(4, confidence=0.95, claim_verification="unverified"),
        requirement_id="req-dist",
        target_topic="backend.distributed",
        completed=True,
        project_target={
            "project_id": target["project_id"],
            "claim_id": target["claim_id"],
            "dimension": target["dimension"],
            "claim_text": target["claim_text"],
        },
    )
    assert merged["project_claim_state"][target["target_id"]]["status"] == "partial"


# --------------------------------------------------------------------------
# 5. Follow-ups stay on the same claim and cap at two
# --------------------------------------------------------------------------


def test_project_followup_keeps_the_same_claim_and_dimension():
    claim = _reliability_claim()
    amap = _attack_map()
    target = next(item for item in amap if item["claim_id"] == claim["claim_id"])
    round_data = {
        "topic": "backend.distributed",
        "competency_id": "backend.distributed",
        "target_requirement_id": "req-dist",
        "question_type": "scenario",
        "followup_count": 0,
        "planner_actions": [
            {
                "selected_action": "verify_project_claim",
                "target_project_id": target["project_id"],
                "target_claim_id": target["claim_id"],
                "project_dimension": target["dimension"],
                "project_followup_depth": 0,
                "supporting_state": {"target_claim_fact": claim["text"], "project_name": "GoTalk", "claim_type": "reliability"},
            }
        ],
    }
    answer_state = {
        **_empty_answer_state(),
        "project_facts": [
            {
                "fact": "Worker 崩溃后通过 Checkpoint 重放恢复",
                "fact_kind": "failure_mode",
                "project_id": target["project_id"],
                "claim_id": target["claim_id"],
                "evidence_span": "Checkpoint 重放恢复",
            }
        ],
    }
    action = choose_after_answer_action(
        [_jd_item(status="pending")],
        initial_candidate_state(amap),
        answer_state,
        _judge(3, missing_points=["未解释故障窗口的数据流"]),
        round_data,
        [],
        remaining_question_budget=5,
        max_followups=2,
        current_difficulty="medium",
    )
    assert action.selected_action == PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value
    assert action.target_project_id == target["project_id"]
    assert action.target_claim_id == target["claim_id"]
    assert action.project_dimension == target["dimension"]
    assert action.project_followup_depth == 1
    assert action.decision_audit.get("followup_source") in {"missing_point", "project_fact"}


def test_generic_project_answer_without_project_fact_gets_a_same_claim_probe():
    claim = _reliability_claim()
    target = next(item for item in _attack_map() if item["claim_id"] == claim["claim_id"])
    round_data = {
        "topic": "backend.distributed",
        "competency_id": "backend.distributed",
        "target_requirement_id": "req-dist",
        "question_type": "scenario",
        "followup_count": 0,
        "planner_actions": [
            {
                "selected_action": "verify_project_claim",
                "target_project_id": target["project_id"],
                "target_claim_id": target["claim_id"],
                "project_dimension": "failure",
                "project_followup_depth": 0,
                "supporting_state": {
                    "target_claim_fact": claim["text"],
                    "project_name": "GoTalk",
                    "claim_type": "reliability",
                },
            }
        ],
    }
    action = choose_after_answer_action(
        [_jd_item(status="pending")],
        initial_candidate_state(_attack_map()),
        _empty_answer_state(),
        _judge(
            3,
            missing_points=["没有说明故障窗口和恢复状态"],
            claim_verification="unverified",
        ),
        round_data,
        [],
        remaining_question_budget=5,
        max_followups=2,
        current_difficulty="medium",
    )
    assert action.selected_action == PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value
    assert action.target_project_id == target["project_id"]
    assert action.target_claim_id == target["claim_id"]
    assert action.project_dimension == "failure"


def test_project_followup_stops_after_two_followups():
    claim = _reliability_claim()
    amap = _attack_map()
    target = next(item for item in amap if item["claim_id"] == claim["claim_id"])
    state = initial_candidate_state(amap)
    round_data = {
        "topic": "backend.distributed",
        "competency_id": "backend.distributed",
        "target_requirement_id": "req-dist",
        "question_type": "scenario",
        "followup_count": PROJECT_CLAIM_MAX_FOLLOWUPS,
        "planner_actions": [
            {
                "selected_action": "follow_up_current_claim",
                "target_project_id": target["project_id"],
                "target_claim_id": target["claim_id"],
                "project_dimension": target["dimension"],
                "project_followup_depth": PROJECT_CLAIM_MAX_FOLLOWUPS,
                "supporting_state": {"target_claim_fact": claim["text"], "project_name": "GoTalk", "claim_type": "reliability"},
            }
        ],
    }
    answer_state = {
        **_empty_answer_state(),
        "project_facts": [
            {
                "fact": "再次给出新的机制细节",
                "fact_kind": "mechanism",
                "project_id": target["project_id"],
                "claim_id": target["claim_id"],
                "evidence_span": "新的机制细节",
            }
        ],
    }
    action = choose_after_answer_action(
        [_jd_item(status="pending")],
        state,
        answer_state,
        _judge(3),
        round_data,
        [],
        remaining_question_budget=5,
        max_followups=PROJECT_CLAIM_MAX_FOLLOWUPS,
        current_difficulty="medium",
    )
    assert not (action.selected_action == PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value and action.target_claim_id == target["claim_id"])


def test_followup_falls_back_to_fact_when_round_has_no_recorded_target():
    claim = _reliability_claim()
    amap = _attack_map()
    target = next(item for item in amap if item["claim_id"] == claim["claim_id"])
    answer_state = {
        **_empty_answer_state(),
        "project_facts": [
            {
                "fact": "超时后进行降级处理",
                "fact_kind": "failure_mode",
                "project_id": target["project_id"],
                "claim_id": target["claim_id"],
                "evidence_span": "超时降级",
            }
        ],
    }
    # Legacy / bare after-answer round carries no project target: the follow-up
    # still probes the newly-introduced project fact on the fact's dimension.
    action = choose_after_answer_action(
        [_jd_item(status="pending")],
        initial_candidate_state(amap),
        answer_state,
        _judge(2),
        {},
        [],
        remaining_question_budget=5,
        max_followups=2,
        current_difficulty="medium",
    )
    assert action.selected_action == PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value
    assert action.target_claim_id == claim["claim_id"]
    assert action.project_dimension == "failure"


def test_followup_fact_from_a_different_claim_never_chains():
    claim = _reliability_claim()
    metric = _metric_claim()
    amap = _attack_map()
    target = next(item for item in amap if item["claim_id"] == claim["claim_id"])
    round_data = {
        "topic": "backend.distributed",
        "competency_id": "backend.distributed",
        "target_requirement_id": "req-dist",
        "question_type": "scenario",
        "followup_count": 0,
        "planner_actions": [
            {
                "selected_action": "verify_project_claim",
                "target_project_id": target["project_id"],
                "target_claim_id": claim["claim_id"],
                "project_dimension": target["dimension"],
                "project_followup_depth": 0,
                "supporting_state": {"target_claim_fact": claim["text"], "project_name": "GoTalk", "claim_type": "reliability"},
            }
        ],
    }
    # The only attributed fact belongs to the OTHER claim of the same project:
    # a follow-up must not switch claims.
    answer_state = {
        **_empty_answer_state(),
        "project_facts": [
            {
                "fact": "GC 分桶细节",
                "fact_kind": "mechanism",
                "project_id": target["project_id"],
                "claim_id": metric["claim_id"],
                "evidence_span": "GC 分桶细节",
            }
        ],
    }
    action = choose_after_answer_action(
        [_jd_item(status="pending")],
        initial_candidate_state(amap),
        answer_state,
        _judge(3),
        round_data,
        [],
        remaining_question_budget=5,
        max_followups=2,
        current_difficulty="medium",
    )
    assert action.selected_action != PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value


# --------------------------------------------------------------------------
# 6. Foundation rounds are never labelled as project deep-dives
# --------------------------------------------------------------------------


def test_foundation_round_is_never_a_project_dive():
    foundation = {
        "question_kind": "foundation",
        "question_type": "scenario",
        "planner_actions": [
            {
                "selected_action": "verify_jd_requirement",
                "target_project_id": "",
                "target_claim_id": "",
                "project_dimension": "",
                "supporting_state": {},
            }
        ],
    }
    classified = question_category_for_round(foundation)
    assert classified["category"] == "foundation"
    assert classified["project_bound"] is False


def test_project_round_is_a_project_dive_only_with_complete_binding():
    claim = _reliability_claim()
    amap = _attack_map()
    target = next(item for item in amap if item["claim_id"] == claim["claim_id"])
    project_round = {
        "question_kind": "adaptive",
        "question_type": "scenario",
        "planner_actions": [
            {
                "selected_action": "verify_project_claim",
                "target_project_id": target["project_id"],
                "target_claim_id": target["claim_id"],
                "project_dimension": target["dimension"],
                "supporting_state": {"target_claim_fact": claim["text"], "project_name": "GoTalk"},
            }
        ],
    }
    classified = question_category_for_round(project_round)
    assert classified["category"] == "project"
    assert classified["project_bound"] is True


# --------------------------------------------------------------------------
# 7. Missing claim-relevant evidence -> reject / downgrade, never fake
# --------------------------------------------------------------------------


def test_claim_irrelevant_evidence_is_rejected_deterministically():
    contract = _contract(_reliability_claim(), "failure", [])
    accepted, rejected = validate_project_evidence([_context_evidence()], contract)
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "claim_irrelevant"


def test_claim_relevant_evidence_is_accepted():
    contract = _contract(_reliability_claim(), "failure", [])
    accepted, rejected = validate_project_evidence([_claim_relevant_evidence()], contract)
    assert [item["evidence_id"] for item in accepted] == ["chunk-ok"]
    assert rejected == []


def test_claim_relevant_but_wrong_dimension_evidence_is_rejected():
    contract = _contract(_reliability_claim(), "failure", [])
    implementation_only = {
        **_claim_relevant_evidence(),
        "content": "Redis Lua 租约通过脚本写入并提交 ACK，Kafka 负责消息投递。",
    }
    accepted, rejected = validate_project_evidence([implementation_only], contract)
    assert accepted == []
    assert rejected[0]["reason"] == "dimension_irrelevant"


def test_generated_project_contract_is_persisted_on_the_round_validation_path():
    from test.unit_test.api.db.test_cs_interview_pipeline import CONFIG, FakeRuntime

    claim = _reliability_claim()
    runtime = FakeRuntime(
        {"experience-ds": [_claim_relevant_evidence()]},
        [
            '{"question_text":"你在 GoTalk 中通过 Redis Lua 租约、ACK Deadline 和 Kafka 保证可靠投递。假设 Worker 写入 Kafka 后宕机，恢复时如何避免重复投递？",'
            '"reference_answer":"Worker 写入 Kafka 后持有 Redis Lua 租约，ACK Deadline 内提交 ACK；宕机恢复后通过租约去重避免重复投递。",'
            '"evaluation_rubric":["说明 Redis Lua 租约","覆盖 ACK Deadline 故障窗口","解释恢复后的去重"]}'
        ],
    )
    config = {**CONFIG, "retrieval_config_snapshot": {}, "feature_flags": {"semantic_dedup": False}}
    snapshot = asyncio_run(
        generate_question(
            runtime,
            "tenant-1",
            {"target_role": "go_backend", "target_level": "mid", "technology_stack": ["Go", "Redis", "Kafka"], "preferred_categories": ["interview_experience"]},
            config,
            [],
            _project_action(claim),
            resume_context=_extraction(),
            job_context=_job(),
        )
    )
    contract = snapshot["question_validation"]["project_contract"]
    assert contract["claim_id"] == claim["claim_id"]
    assert contract["project_dimension"] == "failure"
    assert _project_contract_context(snapshot)["claim_id"] == claim["claim_id"]


def test_unbound_model_followup_falls_back_to_the_same_project_claim():
    from test.unit_test.api.db.test_cs_interview_pipeline import FakeRuntime

    claim = _reliability_claim()
    contract = _contract(claim, "failure", [_claim_relevant_evidence()])
    action = _project_action(claim)
    runtime = FakeRuntime(chat_outputs=['{"question":"解释 context.Context 的取消传播？"}'])
    question = asyncio_run(
        generate_followup(
            runtime,
            "tenant-1",
            {
                "question_text": "原项目问题",
                "reference_answer": "",
                "candidate_answers": [{"answer": "Kafka 能保证可靠投递"}],
                "question_validation": {"project_contract": asdict(contract)},
            },
            action,
        )
    )
    assert "GoTalk" in question
    assert "Redis Lua" in question
    assert "故障" in question or "恢复" in question


def test_project_question_is_never_generated_without_claim_relevant_evidence():
    from test.unit_test.api.db.test_cs_interview_pipeline import CONFIG, PROFILE, FakeRuntime

    claim = _reliability_claim()
    runtime = FakeRuntime({"experience-ds": [_context_evidence()]})
    config = {**CONFIG, "retrieval_config_snapshot": {}, "feature_flags": {"semantic_dedup": False}}
    with pytest.raises(DomainError) as error:
        asyncio_run(
            generate_question(
                runtime,
                "tenant-1",
                {**PROFILE, "target_role": "go_backend", "preferred_categories": ["interview_experience"]},
                config,
                [],
                _project_action(claim),
                resume_context=_extraction(),
                job_context=_job(),
            )
        )
    assert error.value.code == "project_evidence_irrelevant"
    # Non-retryable: handled locally by downgrade, not by the operation retry loop.
    assert classify_failure(error.value).retryable is False


def test_downgrade_produces_a_clearly_marked_foundation_action():
    claim = _reliability_claim()
    action = _project_action(claim)
    downgraded = downgrade_project_action(action)
    assert downgraded.question_kind == "foundation"
    assert downgraded.target_project_id == ""
    assert downgraded.target_claim_id == ""
    assert downgraded.selected_action == PlannerActionKind.VERIFY_JD_REQUIREMENT.value
    assert downgraded.decision_audit.get("downgraded_from_project") is True


def test_planner_skips_targets_without_claim_relevant_evidence():
    claim = _reliability_claim()
    amap = _attack_map()
    target = next(item for item in amap if item["claim_id"] == claim["claim_id"])
    state = initial_candidate_state(amap)
    state["project_claim_state"][target["target_id"]]["evidence_status"] = "unavailable"
    action = choose_planner_action(
        [_jd_item(status="verified", attempt=1)],
        state,
        [],
        remaining_question_budget=3,
        current_difficulty="medium",
    )
    eliminated = [(item.get("target_id"), item.get("reason")) for item in action.decision_audit.get("eliminated", [])]
    assert (target["target_id"], "project_evidence_unavailable") in eliminated


# --------------------------------------------------------------------------
# 8. Metric claims get baseline / variable-control / measurement rubric points
# --------------------------------------------------------------------------


def test_metric_claim_rubric_has_baseline_control_and_measurement():
    contract = _contract(_metric_claim(), "metric")
    kinds = [point["kind"] for point in contract.claim_specific_rubric]
    assert {"metric_baseline", "metric_variable_control", "metric_measurement"} <= set(kinds)
    # Every rubric point references the claim, not a generic competency rubric.
    assert all(point.get("kind") for point in contract.claim_specific_rubric)


def test_failure_dimension_rubric_has_a_failure_window_point():
    contract = _contract(_reliability_claim(), "failure")
    kinds = [point["kind"] for point in contract.claim_specific_rubric]
    assert "failure_window" in kinds


# --------------------------------------------------------------------------
# 9. The report still correlates the right project rounds
# --------------------------------------------------------------------------


def test_report_correlates_claim_specific_verification_rounds():
    from api.apps.services.cs_interview.domain import build_report

    claim = _metric_claim()
    amap = _attack_map()
    target = next(item for item in amap if item["claim_id"] == claim["claim_id"])
    project_target = {
        "project_id": target["project_id"],
        "claim_id": target["claim_id"],
        "dimension": target["dimension"],
        "claim_text": target["claim_text"],
        "question_id": "q-gc",
    }
    specific_fact = {
        "fact": "CityHash 分桶 + Buffer Pool 复用减少堆分配，GC 次数从 192 降到 3",
        "fact_kind": "metric_definition",
        "project_id": target["project_id"],
        "claim_id": target["claim_id"],
        "evidence_span": "CityHash分桶 BufferPool",
    }
    state = merge_candidate_state(
        initial_candidate_state(amap),
        {**_empty_answer_state(), "project_facts": [specific_fact]},
        _judge(4, confidence=0.95),
        requirement_id="req-go",
        target_topic="go.runtime",
        completed=True,
        project_target=project_target,
    )
    round_row = {
        "status": "completed",
        "score": 4,
        "initial_score": 4,
        "followup_count": 0,
        "topic": "go.runtime",
        "difficulty": "medium",
        "category": "interview_experience",
        "competency_id": "go.runtime",
        "question_id": "q-gc",
        "question_kind": "adaptive",
        "judge_confidence": 0.95,
        "evidence_evaluation": {},
        "planner_actions": [
            {
                "target_project_id": target["project_id"],
                "target_claim_id": target["claim_id"],
                "project_dimension": "metric",
            }
        ],
    }
    report = build_report(
        [round_row],
        {"target_role": "go_backend", "initial_difficulty": "medium"},
        resume_snapshot=_extraction(),
        candidate_state=state,
    )
    matrix = report["project_claim_verification"]
    entry = next(item for item in matrix if item["claim_id"] == claim["claim_id"])
    assert entry["verification_status"] == "verified"
    assert entry["score"] == 4.0
    # The untouched reliability claim stays untested even though both belong to
    # the same project.
    reliable = next(item for item in matrix if item["claim_id"] == _reliability_claim()["claim_id"])
    assert reliable["verification_status"] == "untested"


def _asyncio_run(coro):
    import asyncio

    try:
        return asyncio.get_event_loop().run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


asyncio_run = _asyncio_run
