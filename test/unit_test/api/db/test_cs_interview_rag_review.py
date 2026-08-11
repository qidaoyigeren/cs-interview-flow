"""Tests for the 500-case RAG challenge human-review gating.

The generated challenge set must never become resume-eligible until the approved
human review ratio reaches the threshold; partial review must stay gated.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from tools.cs_interview_rag_review import apply_reviews, load_reviews

SAMPLE_CASE = {
    "id": "public-go-leak-001-paraphrase",
    "dataset": "interview_experience",
    "kind": "paraphrase",
    "query": "goroutine 泄漏怎么排查？",
    "expected_question_id": "public-go-leak-001",
    "review_status": "model_generated_unreviewed",
}


def _write_review(lines: list[str]) -> str:
    handle, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(handle, "w", encoding="utf-8") as sink:
        sink.write("\n".join(lines))
    return path


def test_load_reviews_rejects_missing_reviewer_or_bad_status():
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "r.jsonl")
        with open(path, "w", encoding="utf-8") as sink:
            sink.write('{"id": "x", "status": "approved"}\n')
        with pytest.raises(ValueError, match="reviewer_id"):
            load_reviews(path)
        with open(path, "w", encoding="utf-8") as sink:
            sink.write('{"id": "x", "reviewer_id": "a", "status": "maybe"}\n')
        with pytest.raises(ValueError, match="approved|rejected"):
            load_reviews(path)


def test_apply_reviews_records_reviewer_and_gates_resume_eligible():
    cases = [
        {**SAMPLE_CASE},
        {**SAMPLE_CASE, "id": "b", "kind": "scenario"},
        {**SAMPLE_CASE, "id": "c", "kind": "hard"},
    ]
    # Only one of three approved => not resume-eligible.
    reviews = {
        "public-go-leak-001-paraphrase": {"id": "public-go-leak-001-paraphrase", "reviewer_id": "alice", "status": "approved", "note": ""},
        "b": {"id": "b", "reviewer_id": "alice", "status": "rejected", "note": "leaks"},
        "c": {"id": "c", "reviewer_id": "bob", "status": "approved", "note": ""},
    }
    updated, labeling = apply_reviews(cases, reviews)
    assert labeling["reviewed_count"] == 3
    assert labeling["approved_ratio"] == pytest.approx(2 / 3, abs=1e-3)
    assert labeling["resume_eligible"] is False
    by_id = {item["id"]: item for item in updated}
    assert by_id["b"]["reviewer"] == "alice"
    assert by_id["b"]["review_status"] == "human_rejected"
    assert by_id["public-go-leak-001-paraphrase"]["review_status"] == "human_approved"


def test_full_approval_marks_resume_eligible():
    cases = [{**SAMPLE_CASE, "id": f"c{i}"} for i in range(5)]
    reviews = {f"c{i}": {"id": f"c{i}", "reviewer_id": "alice", "status": "approved", "note": ""} for i in range(5)}
    _, labeling = apply_reviews(cases, reviews)
    assert labeling["reviewed_ratio"] == 1.0
    assert labeling["approved_ratio"] == 1.0
    assert labeling["resume_eligible"] is True


def test_apply_reviews_rejects_unknown_case_ids():
    cases = [{**SAMPLE_CASE}]
    reviews = {"unknown-id": {"id": "unknown-id", "reviewer_id": "alice", "status": "approved", "note": ""}}
    with pytest.raises(ValueError, match="unknown case ids"):
        apply_reviews(cases, reviews)
