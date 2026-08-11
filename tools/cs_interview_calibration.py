"""Rubric calibration tool: import, validate and score annotated cases.

Annotation format (one case per entry, at least 3 independent reviewers
recommended before adjudication):

    {
      "schema_version": "cs-interview-annotation-v1",
      "rubric_version": "cs-interview-rubric-v2",
      "model_version": "deepseek-v3",
      "prompt_version": "cs-interview-v1",
      "review_status": "human_reviewed",
      "cases": [
        {
          "case_id": "anno-001",
          "role": "go_backend",
          "competency_id": "go.runtime",
          "anchor_group_id": "anchor-go_backend-go-runtime",
          "question_id": "anchor-go-runtime-q1",
          "candidate_id": "candidate-001",
          "question": "...",
          "answer": "...",
          "code_result": null,
          "rubric_version": "cs-interview-rubric-v2",
          "agent_score": 3,
          "agent_confidence": 0.8,
          "agent_low_confidence": false,
          "agent_followup": true,
          "reviews": [
            {"reviewer_id": "r1", "reviewer_score": 3, "reviewer_evidence_spans": ["s1"], "reviewer_reason": "..."},
            {"reviewer_id": "r2", "reviewer_score": 2, "reviewer_evidence_spans": [], "reviewer_reason": "..."},
            {"reviewer_id": "r3", "reviewer_score": 3, "reviewer_evidence_spans": ["s1"], "reviewer_reason": "..."}
          ],
          "adjudicated_score": 3
        }
      ]
    }

The tool never invents labels: ``adjudicated_score`` must be explicitly present.
Every result reports sample counts, data source, review status, versions and an
``insufficient_sample`` flag instead of a misleading percentage when the sample
is too small.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

SCHEMA_VERSION = "cs-interview-annotation-v1"
MIN_REVIEWERS_PER_CASE = 3
REVIEW_STATUSES = {"synthetic_ci_only", "human_reviewed"}


def validate_annotation_case(item: dict[str, Any], *, path: str) -> list[str]:
    errors: list[str] = []
    for field in ("case_id", "role", "competency_id", "question", "answer", "adjudicated_score"):
        if item.get(field) in (None, ""):
            errors.append(f"{path}: missing required field {field!r}")
    try:
        score = int(item["adjudicated_score"])
        if score not in range(5):
            errors.append(f"{path}: adjudicated_score must be 0..4")
    except (KeyError, TypeError, ValueError):
        pass
    if item.get("agent_score") is not None:
        try:
            if int(item["agent_score"]) not in range(5):
                errors.append(f"{path}: agent_score must be 0..4")
        except (TypeError, ValueError):
            errors.append(f"{path}: agent_score must be an integer")
    reviews = item.get("reviews") or []
    if not isinstance(reviews, list) or not reviews:
        errors.append(f"{path}: at least one reviewer review is required")
    reviewer_ids = set()
    for index, review in enumerate(reviews):
        if not isinstance(review, dict):
            errors.append(f"{path}: review {index} must be an object")
            continue
        reviewer_id = str(review.get("reviewer_id") or "")
        if not reviewer_id:
            errors.append(f"{path}: review {index} lacks reviewer_id")
        if reviewer_id in reviewer_ids:
            errors.append(f"{path}: duplicate reviewer_id {reviewer_id!r}")
        reviewer_ids.add(reviewer_id)
        try:
            if int(review.get("reviewer_score")) not in range(5):
                errors.append(f"{path}: review {index} reviewer_score must be 0..4")
        except (TypeError, ValueError):
            errors.append(f"{path}: review {index} reviewer_score must be an integer")
        if not str(review.get("reviewer_reason") or "").strip():
            errors.append(f"{path}: review {index} lacks reviewer_reason")
    if len(reviewer_ids) < MIN_REVIEWERS_PER_CASE:
        errors.append(f"{path}: at least {MIN_REVIEWERS_PER_CASE} independent reviewers are required per case")
    return errors


def validate_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if payload.get("review_status") not in REVIEW_STATUSES:
        errors.append(f"review_status must be one of {sorted(REVIEW_STATUSES)}")
    cases = payload.get("cases") or []
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty list")
        return errors
    seen_ids: set[str] = set()
    for item in cases:
        path = f"cases[{item.get('case_id', '?')}]"
        errors.extend(validate_annotation_case(item, path=path))
        if payload.get("review_status") == "human_reviewed" and item.get("anchor_group_id"):
            for field in ("question_id", "candidate_id"):
                if not item.get(field):
                    errors.append(f"{path}: human-reviewed anchor cases require {field!r} for repeated-measures stability")
        if item.get("case_id") in seen_ids:
            errors.append(f"{path}: duplicate case_id")
        seen_ids.add(item.get("case_id"))
    return errors


def _print_calibration(result: Any, *, source: str, review_status: str) -> None:
    print(f"Calibration source: {source} | review status: {review_status}")
    print(f"Rubric: {result.versions.get('rubric_version') or 'unknown'} | Model: {result.versions.get('model_version') or 'unknown'} | Prompt: {result.versions.get('prompt_version') or 'unknown'}")
    for name, value in result.metrics.items():
        sample_key = {
            "agent_human_exact_ratio": "agent_human_pairs",
            "agent_human_within_one_ratio": "agent_human_pairs",
            "weighted_cohens_kappa": "agent_human_pairs",
            "macro_f1": "agent_human_pairs",
            "low_confidence_accuracy": "low_confidence_cases",
            "followup_reasonable_ratio": "followup_cases",
            "anchor_coverage_ratio": "anchor_must_have",
            "anchor_group_stability": "anchor_pairs",
            "reviewer_inter_rater_kappa": "reviewer_pairs",
        }.get(name, "cases")
        sample = result.sample_counts.get(sample_key, 0)
        insufficient = result.insufficient.get(name, False)
        marker = "INSUFFICIENT" if insufficient else "ok"
        print(f"  [{marker}] {name}: {value} (n={sample})")
    print("Confusion matrix (rows=human adjudicated, cols=agent):")
    for row in sorted(result.confusion_matrix):
        print(f"    {row}: {result.confusion_matrix[row]}")
    for competency_id, detail in result.per_competency.items():
        flag = "insufficient" if detail["insufficient"] else "ok"
        print(f"  [{flag}] {competency_id}: exact_ratio={detail['agent_human_exact_ratio']} n={detail['case_count']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", nargs="?", default="test/fixtures/cs_interview/calibration_quality.json")
    parser.add_argument("--check", action="store_true", help="Validate only, do not report metrics.")
    parser.add_argument("--source", help="Optional display source; defaults to the fixture path.")
    args = parser.parse_args()

    path = Path(args.fixture)
    if not path.exists():
        print(f"fixture not found: {path}", file=sys.stderr)
        return 1
    with path.open(encoding="utf-8") as source:
        payload = json.load(source)
    errors = validate_payload(payload)
    if errors:
        print("Annotation validation FAILED:")
        for error in errors:
            print(f"  - {error}")
        return 1
    if args.check:
        print("Annotation validation passed.")
        return 0
    # Load only the pure evaluator modules.  Importing the Quart package here
    # would unnecessarily require MySQL/search/native tokenizer dependencies.
    from cs_interview_eval import _load_evaluator

    evaluator = _load_evaluator()
    result = evaluator.evaluate_calibration(payload)
    _print_calibration(
        result,
        source=args.source or str(path),
        review_status=str(payload["review_status"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
