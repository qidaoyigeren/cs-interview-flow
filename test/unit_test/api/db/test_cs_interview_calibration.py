"""Rubric calibration metrics and annotation format tests.

All tests are pure (no LLM / DB). The calibration fixture is small and
synthetic; every test asserts ``insufficient_sample`` rather than a fabricated
percentage when the sample is too small.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.apps.services.cs_interview.evaluation import (
    _confusion_matrix,
    _macro_f1,
    _weighted_cohens_kappa,
    evaluate_calibration,
)
from tools.cs_interview_calibration import validate_annotation_case, validate_payload

FIXTURE = Path(__file__).resolve().parents[4] / "test" / "fixtures" / "cs_interview" / "calibration_quality.json"


def _case(**overrides):
    base = {
        "case_id": "cal-test-001",
        "role": "go_backend",
        "competency_id": "go.runtime",
        "anchor_group_id": "anchor-go_backend-go-runtime",
        "question_id": "anchor-q1",
        "candidate_id": "candidate-a",
        "question": "q",
        "answer": "a",
        "code_result": None,
        "rubric_version": "cs-interview-rubric-v2",
        "agent_score": 3,
        "agent_confidence": 0.8,
        "agent_low_confidence": False,
        "agent_followup": False,
        "reviews": [
            {"reviewer_id": "r1", "reviewer_score": 3, "reviewer_evidence_spans": ["a"], "reviewer_reason": "ok"},
            {"reviewer_id": "r2", "reviewer_score": 3, "reviewer_evidence_spans": [], "reviewer_reason": "ok"},
            {"reviewer_id": "r3", "reviewer_score": 2, "reviewer_evidence_spans": [], "reviewer_reason": "disagree"},
        ],
        "adjudicated_score": 3,
    }
    base.update(overrides)
    return base


def test_annotation_case_validation_requires_fields_reviewers_and_score_range():
    assert validate_annotation_case(_case(), path="cases[x]") == []
    missing_adjudicated = _case(adjudicated_score=None)
    assert any("adjudicated_score" in error for error in validate_annotation_case(missing_adjudicated, path="cases[x]"))
    bad_score = _case(adjudicated_score=9)
    assert any("0..4" in error for error in validate_annotation_case(bad_score, path="cases[x]"))
    duplicate_reviewer = _case(reviews=[*_case()["reviews"], {"reviewer_id": "r1", "reviewer_score": 3, "reviewer_evidence_spans": [], "reviewer_reason": "dup"}])
    assert any("duplicate reviewer_id" in error for error in validate_annotation_case(duplicate_reviewer, path="cases[x]"))
    single_reviewer = _case(reviews=_case()["reviews"][:1])
    assert any("3 independent reviewers" in error for error in validate_annotation_case(single_reviewer, path="cases[x]"))
    no_reason = _case(reviews=[{**review, "reviewer_reason": ""} for review in _case()["reviews"]])
    assert any("reviewer_reason" in error for error in validate_annotation_case(no_reason, path="cases[x]"))


def test_calibration_payload_requires_schema_version_and_non_empty_cases():
    errors = validate_payload({"schema_version": "wrong", "cases": []})
    assert any("schema_version" in error for error in errors)
    assert any("non-empty" in error for error in errors)
    good = {"schema_version": "cs-interview-annotation-v1", "review_status": "synthetic_ci_only", "cases": [_case()]}
    assert validate_payload(good) == []


def test_calibration_metrics_match_hand_computed_values():
    # exact=2, within_one=3, weighted kappa over 3 pairs, macro F1 from matrix
    cases = [
        _case(case_id="c1", adjudicated_score=3, agent_score=3),
        _case(case_id="c2", adjudicated_score=3, agent_score=2),
        _case(case_id="c3", adjudicated_score=2, agent_score=2),
    ]
    payload = {"schema_version": "cs-interview-annotation-v1", "review_status": "synthetic_ci_only", "rubric_version": "r1", "model_version": "m1", "prompt_version": "p1", "cases": cases}
    result = evaluate_calibration(payload)
    assert result.metrics["agent_human_exact_ratio"] == pytest.approx(2 / 3, abs=1e-3)
    assert result.metrics["agent_human_within_one_ratio"] == 1.0
    assert result.metrics["weighted_cohens_kappa"] == _weighted_cohens_kappa([(3, 3), (3, 2), (2, 2)])
    assert result.metrics["macro_f1"] == _macro_f1(_confusion_matrix([(3, 3), (3, 2), (2, 2)]))
    assert result.sample_counts["agent_human_pairs"] == 3
    assert result.confusion_matrix["3"]["2"] == 1
    # n=3 below the production floor => insufficient for the ratio metrics.
    assert result.insufficient["agent_human_exact_ratio"] is True


def test_calibration_metrics_insufficient_with_zero_or_tiny_samples():
    empty = evaluate_calibration({"schema_version": "cs-interview-annotation-v1", "review_status": "synthetic_ci_only", "cases": []})
    assert empty.sample_counts["cases"] == 0
    assert empty.insufficient["agent_human_exact_ratio"] is True
    assert empty.insufficient["low_confidence_accuracy"] is True
    one = evaluate_calibration({"schema_version": "cs-interview-annotation-v1", "review_status": "synthetic_ci_only", "cases": [_case(adjudicated_score=3, agent_score=3)]})
    assert one.insufficient["agent_human_exact_ratio"] is True


def test_fixture_calibration_file_validates_and_reports_versions():
    with FIXTURE.open(encoding="utf-8") as source:
        payload = json.load(source)
    assert validate_payload(payload) == []
    result = evaluate_calibration(payload)
    assert payload["review_status"] == "synthetic_ci_only"
    assert result.versions["rubric_version"] == "cs-interview-rubric-v2"
    assert result.sample_counts["cases"] == 8
    assert result.sample_counts["reviewer_pairs"] == 24
    assert result.metrics["agent_human_exact_ratio"] >= 0.0
    assert result.sample_counts["anchor_pairs"] == 0
    assert result.insufficient["agent_human_exact_ratio"] is True
    assert result.insufficient["anchor_group_stability"] is True


def test_anchor_stability_uses_same_candidate_on_distinct_questions_only():
    cases = [
        _case(case_id="a1", question_id="anchor-q1", candidate_id="same", adjudicated_score=3),
        _case(case_id="a2", question_id="anchor-q2", candidate_id="same", adjudicated_score=4),
        _case(case_id="other", question_id="anchor-q2", candidate_id="different", adjudicated_score=0),
    ]
    result = evaluate_calibration({"schema_version": "cs-interview-annotation-v1", "review_status": "synthetic_ci_only", "cases": cases})
    assert result.sample_counts["anchor_pairs"] == 1
    assert result.metrics["anchor_group_stability"] == 1.0


def test_inter_rater_pairs_compare_reviewers_not_adjudication():
    result = evaluate_calibration({"schema_version": "cs-interview-annotation-v1", "review_status": "synthetic_ci_only", "cases": [_case()]})
    assert result.sample_counts["reviewer_pairs"] == 3


def test_weighted_cohens_kappa_is_sensitive_to_disagreement():
    perfect = _weighted_cohens_kappa([(3, 3), (2, 2), (1, 1)])
    assert perfect == 1.0
    inverted = _weighted_cohens_kappa([(3, 1), (2, 4), (1, 3)])
    assert inverted is not None and inverted < 0.5
    assert _weighted_cohens_kappa([]) is None
