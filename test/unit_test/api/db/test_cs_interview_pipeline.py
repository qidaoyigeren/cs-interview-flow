import asyncio
import json

import pytest

from api.apps.services.cs_interview.domain import DomainError, PlannerAction, PlannerActionKind, evaluation_to_judge_result
from api.apps.services.cs_interview.judge import evaluate_answer
from api.apps.services.cs_interview.observability import OperationContext, operation_context
from api.apps.services.cs_interview.pipeline import _safe_model_snapshot, generate_question


class FakeRuntime:
    def __init__(self, evidence_by_dataset=None, chat_outputs=None):
        self.evidence_by_dataset = evidence_by_dataset or {}
        self.chat_outputs = list(chat_outputs or [])
        self.retrieval_calls = []
        self.chat_calls = []

    async def retrieve(self, tenant_id, dataset_id, query, config):
        self.retrieval_calls.append((tenant_id, dataset_id, query, config))
        return self.evidence_by_dataset.get(dataset_id, [])

    async def chat(self, tenant_id, system, user, *, temperature=0.1):
        self.chat_calls.append((system, user, temperature))
        return self.chat_outputs.pop(0), "fake-model-v1"

    async def embed(self, tenant_id, texts):
        return [[float(index == item_index) for index in range(len(texts))] for item_index, _ in enumerate(texts)]

    def model_snapshot(self, tenant_id):
        return {"chat": {"model": "fake"}}


def _evidence(question_id="go-runtime-001"):
    return {
        "evidence_id": "chunk-1",
        "dataset_id": "fundamentals-ds",
        "document_id": "doc-1",
        "document_name": "Synthetic Go runtime notes",
        "content": (
            "Sending to a closed Go channel panics. Receiving first drains buffered values, then returns the zero value "
            "with ok=false. These rules make closed-channel send and receive behavior deterministic."
        ),
        "similarity": 0.92,
        "metadata": {
            "content_type": "fundamentals",
            "role": "go_backend",
            "topic": "go.runtime",
            "difficulty": "medium",
            "question_id": question_id,
            "source": "synthetic-fixture",
            "source_date": "2026-01-01",
            "quality_score": 0.95,
            "verified": True,
            "license": "CC0",
        },
    }


def _experience_evidence():
    item = _evidence("go-runtime-experience-001")
    item["dataset_id"] = "experience-ds"
    item["content"] = (
        "Diagnose a goroutine blocked on a channel by inspecting goroutine profiles and blocking stack traces, then check channel ownership and cancellation propagation before changing code."
    )
    item["metadata"] = {
        **item["metadata"],
        "content_type": "interview_experience",
    }
    return item


PROFILE = {
    "target_role": "go_backend",
    "target_level": "mid",
    "technology_stack": ["Go"],
    "focus_topics": ["go.runtime"],
    "excluded_topics": [],
    "preferred_categories": ["baguwen"],
}
CONFIG = {
    "interview_experience_dataset_id": "experience-ds",
    "leetcode_dataset_id": "leetcode-ds",
    "fundamentals_dataset_id": "fundamentals-ds",
    "retrieval_config_snapshot": {"top_n": 5},
}


def _planner_action(topic="go.runtime", difficulty="medium", preferred_question_type="scenario"):
    return PlannerAction(
        selected_action=(PlannerActionKind.ASK_CODING_QUESTION.value if preferred_question_type == "coding" else PlannerActionKind.VERIFY_JD_REQUIREMENT.value),
        target_requirement_id=None,
        target_topic=topic,
        reason="Unit-test planner action",
        supporting_state={},
        target_difficulty=difficulty,
        preferred_question_type=preferred_question_type,
    )


def test_model_snapshot_never_persists_credentials():
    snapshot = _safe_model_snapshot(
        {
            "model": "safe-model",
            "api_key": "secret-a",
            "headers": {"Authorization": "Bearer secret-b"},
            "nested": {"client_secret": "secret-c", "max_tokens": 1000},
        }
    )
    assert snapshot == {"model": "safe-model", "headers": {}, "nested": {"max_tokens": 1000}}


def test_prompt_variant_changes_the_executed_prompt_and_snapshot_version():
    runtime = FakeRuntime(
        {"fundamentals-ds": [_evidence()]},
        [
            json.dumps(
                {
                    "question_text": "What happens when sending to and receiving from a closed Go channel?",
                    "reference_answer": "Sending panics; receiving drains buffered values, then returns zero with ok false.",
                    "evaluation_rubric": ["send behavior", "receive behavior"],
                }
            )
        ],
    )
    token = operation_context.set(
        OperationContext(
            tenant_id="tenant-1",
            user_id="user-1",
            session_id="session-1",
            operation_id="operation-1",
            request_id="request-1",
            prompt_version="cs-interview-v2",
            runtime_config={"feature_flags": {"semantic_dedup": False}},
        )
    )
    try:
        snapshot = asyncio.run(generate_question(runtime, "tenant-1", PROFILE, CONFIG, [], _planner_action()))
    finally:
        operation_context.reset(token)

    assert snapshot["prompt_version"] == "cs-interview-v2"
    assert "Prefer a concrete production scenario" in runtime.chat_calls[0][0]


def test_question_pipeline_routes_to_one_dataset_when_evidence_is_sufficient():
    question = {
        "question_text": "What happens when sending to and receiving from a closed Go channel?",
        "reference_answer": "Sending panics; receiving drains buffered values, then returns the zero value with ok false.",
        "evaluation_rubric": ["send behavior", "receive behavior"],
    }
    runtime = FakeRuntime(
        {"fundamentals-ds": [_evidence()]},
        [json.dumps(question)],
    )
    snapshot = asyncio.run(generate_question(runtime, "tenant-1", PROFILE, CONFIG, [], _planner_action()))
    assert snapshot["question_id"] == "go-runtime-001"
    assert snapshot["reference_answer"]
    assert [call[1] for call in runtime.retrieval_calls] == ["fundamentals-ds"]
    conditions = runtime.retrieval_calls[0][3]["meta_data_filter"]["manual"]
    assert {item["key"] for item in conditions} >= {
        "content_type",
        "role",
        "topic",
        "difficulty",
        "verified",
        "quality_score",
    }


def test_anchor_question_requires_evidence_from_the_frozen_group():
    anchor_id = "anchor-go_backend-go-runtime"
    action = PlannerAction(
        selected_action=PlannerActionKind.VERIFY_JD_REQUIREMENT.value,
        target_requirement_id=None,
        target_topic="go.runtime",
        reason="anchor baseline",
        supporting_state={},
        target_difficulty="medium",
        preferred_question_type="scenario",
        question_kind="anchor",
        competency_id="go.runtime",
        anchor_group_id=anchor_id,
        expected_evidence={
            "anchor_content_type": "fundamentals",
            "anchor_difficulty": "medium",
            "anchor_question_ids": ["public-fund-context-001"],
        },
    )
    wrong_group = _evidence("public-fund-context-001")
    wrong_group["metadata"]["anchor_group_id"] = "another-group"
    runtime = FakeRuntime({"fundamentals-ds": [wrong_group]})

    with pytest.raises(DomainError, match="no verified"):
        asyncio.run(generate_question(runtime, "tenant-1", PROFILE, CONFIG, [], action))

    assert runtime.chat_calls == []
    assert len(runtime.retrieval_calls) == 2
    for call in runtime.retrieval_calls:
        filters = call[3]["meta_data_filter"]["manual"]
        assert {item["key"]: item["value"] for item in filters}["anchor_group_id"] == anchor_id


def test_anchor_question_uses_reviewed_canonical_text_without_an_llm_rewrite():
    anchor_id = "anchor-go_backend-go-runtime"
    evidence = _evidence("public-fund-context-001")
    evidence["metadata"]["anchor_group_id"] = anchor_id
    evidence["content"] = """# Go context
## 问题
解释 context 的取消传播、deadline 和资源释放边界。
## 参考要点
- 父 context 取消会传播给派生子 context。
- WithCancel 返回的 cancel 应及时调用以释放 timer 和引用。
"""
    action = PlannerAction(
        selected_action=PlannerActionKind.VERIFY_JD_REQUIREMENT.value,
        target_requirement_id=None,
        target_topic="go.runtime",
        reason="anchor baseline",
        supporting_state={},
        target_difficulty="medium",
        preferred_question_type="scenario",
        question_kind="anchor",
        competency_id="go.runtime",
        anchor_group_id=anchor_id,
        expected_evidence={
            "anchor_content_type": "fundamentals",
            "anchor_difficulty": "medium",
            "anchor_question_ids": ["public-fund-context-001"],
        },
    )
    runtime = FakeRuntime({"fundamentals-ds": [evidence]})

    snapshot = asyncio.run(generate_question(runtime, "tenant-1", PROFILE, CONFIG, [], action))

    assert snapshot["question_text"] == "解释 context 的取消传播、deadline 和资源释放边界。"
    assert snapshot["model_version"] == "reviewed-anchor-v1"
    assert runtime.chat_calls == []


def test_governance_blocked_question_never_reaches_the_model():
    runtime = FakeRuntime(
        {"fundamentals-ds": [_evidence("question-blocked")]},
        [json.dumps({"question_text": "must not be used"})],
    )
    config = {**CONFIG, "blocked_question_ids": ["question-blocked"]}

    with pytest.raises(DomainError):
        asyncio.run(generate_question(runtime, "tenant-1", PROFILE, config, [], _planner_action()))

    assert runtime.chat_calls == []


def test_algorithm_retrieval_uses_one_role_neutral_corpus():
    evidence = _evidence("shared-algorithm-001")
    evidence["dataset_id"] = "leetcode-ds"
    evidence["document_name"] = "Shared algorithm question"
    evidence["metadata"] = {
        **evidence["metadata"],
        "content_type": "leetcode",
        "role": "cs_general",
        "topic": "algorithm.core",
    }
    evidence["content"] = (
        "A linear-time array solution uses a hash table to retain prior values and returns the matching indices.\n"
        "## 标准解法\n- Use a hash table and check each complement before insertion.\n"
        "## 评分点\n- Return correct indices in O(n) time."
    )
    profile = {
        **PROFILE,
        "focus_topics": ["algorithm.core"],
        "preferred_categories": ["leetcode"],
    }
    question = {
        "question_text": "Implement a linear-time solution for the supplied array problem.",
        "reference_answer": "Use a hash table to retain the necessary prior values and return the matching indices.",
        "evaluation_rubric": ["linear time", "correct indices"],
        "code_spec": {
            "function_name": "solve",
            "visible_tests": [{"input": [1, 2], "expected": [0, 1]}],
            "hidden_tests": [{"input": [2, 3], "expected": [0, 1]}],
            "constraints": "At least two values.",
            "complexity_expectation": "O(n)",
            "language": "python",
            "reference_solution": "def solve(values):\n    return [0, 1]",
        },
    }
    runtime = FakeRuntime({"leetcode-ds": [evidence]}, [json.dumps(question)])

    snapshot = asyncio.run(
        generate_question(
            runtime,
            "tenant-1",
            profile,
            CONFIG,
            [],
            _planner_action("algorithm.core", preferred_question_type="coding"),
        )
    )

    assert snapshot["question_id"] == "shared-algorithm-001"
    conditions = runtime.retrieval_calls[0][3]["meta_data_filter"]["manual"]
    role_filter = next(item for item in conditions if item["key"] == "role")
    assert role_filter["value"] == "cs_general"


def test_question_pipeline_never_generates_without_verified_evidence():
    runtime = FakeRuntime({})
    with pytest.raises(DomainError) as error:
        asyncio.run(generate_question(runtime, "tenant-1", PROFILE, CONFIG, [], _planner_action()))
    assert error.value.code in {"insufficient_evidence", "no_eligible_topic"}
    assert runtime.chat_calls == []


def test_question_pipeline_rejects_technical_premise_absent_from_evidence():
    ungrounded = {
        "question_text": "Explain Kubernetes control-plane certificate rotation and etcd quorum recovery.",
        "reference_answer": "Sending panics; receiving drains buffered values, then returns zero with ok false.",
        "evaluation_rubric": ["send behavior", "receive behavior"],
    }
    runtime = FakeRuntime(
        {"fundamentals-ds": [_evidence()]},
        [json.dumps(ungrounded), json.dumps(ungrounded)],
    )

    with pytest.raises(DomainError) as error:
        asyncio.run(generate_question(runtime, "tenant-1", PROFILE, CONFIG, [], _planner_action()))

    assert error.value.code == "insufficient_evidence"
    assert len(runtime.chat_calls) == 2


def test_question_pipeline_rejects_topic_not_mapped_to_selected_jd_requirement():
    question = {
        "question_text": "What happens when sending to and receiving from a closed Go channel?",
        "reference_answer": "Sending panics; receiving drains buffered values, then returns zero with ok false.",
        "evaluation_rubric": ["send behavior", "receive behavior"],
    }
    runtime = FakeRuntime({"fundamentals-ds": [_evidence()]}, [json.dumps(question)])
    action = PlannerAction(
        selected_action=PlannerActionKind.VERIFY_JD_REQUIREMENT.value,
        target_requirement_id="req-rag",
        target_topic="go.runtime",
        reason="invalid test mapping",
        supporting_state={},
        target_difficulty="medium",
    )

    with pytest.raises(DomainError) as error:
        asyncio.run(
            generate_question(
                runtime,
                "tenant-1",
                PROFILE,
                CONFIG,
                [],
                action,
                job_context={
                    "extraction": {
                        "requirements": [
                            {
                                "requirement_id": "req-rag",
                                "text": "Build RAG services",
                                "topic_ids": ["ai.rag"],
                            }
                        ]
                    }
                },
            )
        )

    assert error.value.code == "jd_irrelevant_question"


def test_question_pipeline_retries_incomplete_model_output():
    valid = {
        "question_text": "What happens when a Go channel is closed for senders and receivers?",
        "reference_answer": "Sending panics; receiving drains buffered values and then returns the zero value with ok false.",
        "evaluation_rubric": ["send behavior", "receive behavior"],
    }
    runtime = FakeRuntime(
        {"fundamentals-ds": [_evidence()]},
        [json.dumps({"question_text": "too short"}), json.dumps(valid)],
    )

    snapshot = asyncio.run(generate_question(runtime, "tenant-1", PROFILE, CONFIG, [], _planner_action()))

    assert snapshot["question_id"] == "go-runtime-001"
    assert len(runtime.chat_calls) == 2


def test_question_pipeline_uses_second_dataset_only_after_query_rewrite_fails():
    runtime = FakeRuntime(
        {"experience-ds": [_experience_evidence()]},
        [
            json.dumps(
                {
                    "question_text": "In production, how would you diagnose a goroutine blocked on a channel?",
                    "reference_answer": "Inspect goroutine profiles, channel ownership, cancellation, and blocking stack traces before changing code.",
                    "evaluation_rubric": ["goroutine profile", "ownership", "cancellation"],
                }
            )
        ],
    )
    snapshot = asyncio.run(generate_question(runtime, "tenant-1", PROFILE, CONFIG, [], _planner_action()))
    assert snapshot["category"] == "interview_experience"
    assert [call[1] for call in runtime.retrieval_calls] == [
        "fundamentals-ds",
        "fundamentals-ds",
        "experience-ds",
    ]


def test_question_pipeline_rejects_exact_question_id_reuse():
    runtime = FakeRuntime(
        {"fundamentals-ds": [_evidence()]},
        [
            json.dumps(
                {
                    "question_text": "What happens when sending to and receiving from a closed Go channel?",
                    "reference_answer": "Sending panics; receiving eventually returns a zero value with ok false.",
                    "evaluation_rubric": ["send behavior", "receive behavior"],
                }
            )
        ]
        * 8,
    )
    with pytest.raises(DomainError):
        asyncio.run(
            generate_question(
                runtime,
                "tenant-1",
                PROFILE,
                CONFIG,
                [{"question_id": "go-runtime-001", "question_text": "A previous question", "topic": "go.runtime"}],
                _planner_action(),
            )
        )
    assert runtime.chat_calls == []


_EXTRACTION_JSON = {
    "answer_spans": [{"span_id": "s1", "text": "Sending to a closed channel panics"}],
    "technical_claims": [{"claim_id": "c1", "text": "send on a closed channel panics", "span_ids": ["s1"], "topic_ids": ["go.runtime"]}],
    "decisions": [],
    "mechanisms": [],
    "tradeoffs": [],
    "examples": [],
    "contradictions": [],
    "uncertainty_phrases": [],
    "matched_indicators": [{"indicator": "核心概念与典型实现", "anchor_level": 2, "span_ids": ["s1"]}],
    "missing_indicators": [{"indicator": "机制解释与场景权衡", "anchor_level": 3}],
    "newly_claimed_facts": [],
    "project_facts": [],
    "covered_rubric_points": [],
    "unverified_boundaries": [],
    "deep_dive_branches": [],
}


def _round_data():
    return {
        "question_text": "Explain a closed channel.",
        "reference_answer": "Reference answer with evidence.",
        "evaluation_rubric": ["send behavior", "receive behavior"],
        "candidate_answers": [{"answer": "Sending to a closed channel panics"}],
        "followup_count": 0,
        "topic": "go.runtime",
        "difficulty": "medium",
        "question_type": "theory",
        "question_kind": "adaptive",
    }


def test_evidence_judge_happy_path_produces_judge_result():
    scorer = {
        "score": 2,
        "matched_anchor": 2,
        "verdict": "partial",
        "matched_indicators": ["核心概念与典型实现"],
        "missing_indicators": ["机制解释与场景权衡"],
        "evidence_span_ids": ["s1"],
        "confidence": 0.8,
        "needs_followup": False,
        "followup_focus": "",
        "weak_point": "",
        "feedback": "Correct basic mechanism.",
        "evaluation_summary": "Basic mechanism.",
        "factual_errors": [],
    }
    runtime = FakeRuntime(chat_outputs=[json.dumps(_EXTRACTION_JSON), json.dumps(scorer)])
    evaluation = asyncio.run(
        evaluate_answer(
            runtime,
            "tenant-1",
            answer="Sending to a closed channel panics",
            round_data=_round_data(),
            rubric_snapshot=None,
            code_result=None,
            history=[],
            max_followups=2,
        )
    )
    result = evaluation_to_judge_result(evaluation)
    assert len(runtime.chat_calls) == 2
    assert result.score == 2
    assert result.verdict == "partial"
    assert result.covered_points == ["核心概念与典型实现"]
    assert result.missing_points == ["机制解释与场景权衡"]


def test_evidence_judge_low_confidence_after_consistency_failure():
    # The scorer passes JSON but is internally inconsistent (cites an indicator
    # that the extractor never found). Consistency validation fails, the scorer
    # is retried once, and the result becomes low-confidence -- never a
    # fabricated deterministic score.
    bad_scorer = {
        "score": 4,
        "matched_anchor": 4,
        "verdict": "excellent",
        "matched_indicators": ["invented indicator not in the answer"],
        "missing_indicators": [],
        "evidence_span_ids": ["s1"],
        "confidence": 0.9,
        "needs_followup": False,
        "followup_focus": "",
        "weak_point": "",
        "feedback": "Looks complete.",
        "evaluation_summary": "Complete.",
        "factual_errors": [],
    }
    runtime = FakeRuntime(chat_outputs=[json.dumps(_EXTRACTION_JSON), json.dumps(bad_scorer), json.dumps(bad_scorer)])
    evaluation = asyncio.run(
        evaluate_answer(
            runtime,
            "tenant-1",
            answer="Sending to a closed channel panics",
            round_data=_round_data(),
            rubric_snapshot=None,
            code_result=None,
            history=[],
            max_followups=2,
        )
    )
    assert len(runtime.chat_calls) == 3  # extractor + scorer + one retry
    assert evaluation.low_confidence is True
    assert evaluation.validator["passed"] is False
    assert evaluation.validator["retried"] is True
    assert evaluation.scorer["confidence"] <= 0.3
    assert evaluation.scorer["needs_followup"] is False
    assert "低置信" in evaluation.scorer["feedback"] or "low-confidence" in evaluation.scorer["feedback"]
