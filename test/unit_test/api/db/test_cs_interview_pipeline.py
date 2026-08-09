import asyncio
import json

import pytest

from api.apps.services.cs_interview.domain import DomainError, PlannerAction, PlannerActionKind
from api.apps.services.cs_interview.observability import OperationContext, operation_context
from api.apps.services.cs_interview.pipeline import _safe_model_snapshot, generate_question, judge_answer


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


def test_low_confidence_judge_runs_twice_and_uses_conservative_result():
    low_confidence = {
        "score": 4,
        "verdict": "excellent",
        "covered_points": ["all"],
        "missing_points": [],
        "factual_errors": [],
        "needs_followup": False,
        "followup_focus": "",
        "weak_point": "",
        "feedback": "Looks complete.",
        "evaluation_summary": "Complete.",
        "confidence": 0.3,
    }
    runtime = FakeRuntime(chat_outputs=[json.dumps(low_confidence), json.dumps(low_confidence)])
    result = asyncio.run(
        judge_answer(
            runtime,
            "tenant-1",
            {
                "question_text": "Explain a closed channel.",
                "reference_answer": "Reference answer with evidence.",
                "evaluation_rubric": ["send behavior", "receive behavior"],
                "candidate_answers": [{"answer": "Candidate answer"}],
                "followup_count": 0,
            },
            [],
            2,
        )
    )
    assert len(runtime.chat_calls) == 2
    assert result.score == 2
    assert result.verdict == "partial"
    assert not result.needs_followup
    assert "send behavior" in result.feedback
