import json
from pathlib import Path

from api.apps.services.cs_interview.evaluation import evaluate_file, evaluate_fixture


def test_synthetic_offline_fixture_is_computed_and_meets_gate():
    fixture = Path("test/fixtures/cs_interview/offline_eval.json")
    result = evaluate_file(fixture)
    assert result.sample_counts == {
        "retrieval_cases": 6,
        "question_cases": 6,
        "judge_cases": 6,
        "report_cases": 1,
        "visibility_cases": 1,
        "agentic_cases": 50,
        "agentic_requirements": 44,
        "agentic_resume_claims": 19,
    }
    assert result.metrics["retrieval_recall_at_5"] == 1.0
    assert result.metrics["question_duplicate_ratio"] == 0
    assert result.metrics["hidden_answer_leakage_count"] == 0
    assert result.metrics["answer_driven_branch_accuracy"] == 1
    assert result.metrics["contradiction_followup_accuracy"] == 1
    assert result.metrics["replay_determinism_ratio"] == 1.0
    assert result.thresholds["jd_requirement_question_coverage"]["passed"]
    assert result.thresholds["resume_claim_verification_rate"]["passed"]
    assert result.thresholds["replay_determinism_ratio"]["passed"]
    # Project deep-dive metrics must pass on the project scenarios.
    assert result.thresholds["project_claim_coverage"]["passed"]
    assert result.thresholds["project_claim_verification_accuracy"]["passed"]
    assert result.thresholds["project_followup_relevance"]["passed"]
    assert result.thresholds["metric_verification_accuracy"]["passed"]
    assert result.thresholds["cross_project_leakage"]["passed"]
    assert result.thresholds["project_replay_consistency"]["passed"]
    assert result.thresholds["project_claim_verification_accuracy"]["sample_count"] == 7
    assert result.thresholds["project_claim_verification_accuracy"]["ci"]["point"] == 1.0
    # Threshold rows carry the sample count and a Wilson CI.
    assert result.thresholds["retrieval_recall_at_5"]["sample_count"] == 6
    assert result.thresholds["retrieval_recall_at_5"]["ci"]["low"] <= 1.0 <= result.thresholds["retrieval_recall_at_5"]["ci"]["high"]
    assert result.passed


def test_agentic_gate_executes_planner_and_detects_a_regression():
    with Path("test/fixtures/cs_interview/offline_eval.json").open(encoding="utf-8") as fixture:
        payload = json.load(fixture)
    with Path("test/fixtures/cs_interview/agentic_scenarios.json").open(encoding="utf-8") as fixture:
        agentic = json.load(fixture)
    assert all("actual_action" not in case for case in agentic["agentic_cases"])
    assert all("asked_requirement_ids" not in case for case in agentic["agentic_cases"])
    assert all(
        "verification_status" not in claim
        for case in agentic["agentic_cases"]
        for claim in case.get("resume_claims", [])
    )
    for case in agentic["agentic_cases"]:
        planner = case["planner"]
        planner["plan"] = []
        planner["answer_state"] = {"newly_claimed_facts": [], "contradictions": []}
    payload["agentic_cases"] = agentic["agentic_cases"]

    result = evaluate_fixture(payload)

    assert result.metrics["answer_driven_branch_accuracy"] < 0.85
    assert not result.thresholds["answer_driven_branch_accuracy"]["passed"]
    assert result.metrics["replay_determinism_ratio"] == 1.0
    assert result.thresholds["replay_determinism_ratio"]["passed"]
    assert not result.passed


def test_insufficient_samples_never_pass_the_gate():
    payload = {
        "retrieval_cases": [{"query": "q", "expected_ids": ["a"], "retrieved_ids": ["a"]}],
        "questions": [
            {"question_id": "q1", "question_text": "t", "role": "go_backend", "topic": "go.runtime", "difficulty": "medium", "requested_difficulty": "medium", "evidence_valid": True}
        ],
        "judge_cases": [],
        "report_cases": [],
        "candidate_responses": [],
        "agentic_cases": [],
    }
    result = evaluate_fixture(payload)
    assert not result.passed
    assert result.insufficient["retrieval_recall_at_5"] is True
    assert result.insufficient["judge_human_agreement_ratio"] is True
    # A metric with zero samples must report insufficient, not a trivial pass.
    assert not result.thresholds["retrieval_recall_at_5"]["passed"]


def test_zero_sample_safety_metrics_force_failure():
    payload = {
        "retrieval_cases": [],
        "questions": [],
        "judge_cases": [],
        "report_cases": [],
        "candidate_responses": [],
        "agentic_cases": [],
    }
    result = evaluate_fixture(payload)
    for name in ("hidden_answer_leakage_count", "ungrounded_generation_count", "replay_determinism_ratio"):
        assert result.insufficient[name] is True
        assert not result.thresholds[name]["passed"]
    assert not result.passed


def test_expected_action_label_does_not_define_replay_determinism():
    with Path("test/fixtures/cs_interview/offline_eval.json").open(encoding="utf-8") as fixture:
        payload = json.load(fixture)
    agentic = json.loads(Path("test/fixtures/cs_interview/agentic_scenarios.json").read_text(encoding="utf-8"))
    cases = agentic["agentic_cases"]
    cases[0]["expected_action"] = "finish_interview"  # sabotage one label
    payload["agentic_cases"] = cases
    result = evaluate_fixture(payload)
    assert result.metrics["answer_driven_branch_accuracy"] < 1.0
    assert result.metrics["replay_determinism_ratio"] == 1.0
    assert result.thresholds["replay_determinism_ratio"]["passed"]


def test_replay_gate_uses_the_replay_implementation(monkeypatch):
    import api.apps.services.cs_interview.evaluation as evaluation_module

    with Path("test/fixtures/cs_interview/offline_eval.json").open(encoding="utf-8") as fixture:
        payload = json.load(fixture)
    agentic = json.loads(Path("test/fixtures/cs_interview/agentic_scenarios.json").read_text(encoding="utf-8"))
    payload["agentic_cases"] = agentic["agentic_cases"]
    monkeypatch.setattr(evaluation_module, "replay_planner_decision", lambda **_kwargs: {"outcome": "changed"})

    result = evaluate_fixture(payload)

    assert result.metrics["replay_determinism_ratio"] == 0.0
    assert not result.thresholds["replay_determinism_ratio"]["passed"]
