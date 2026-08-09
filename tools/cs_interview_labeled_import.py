"""Import and validate the human-labeled quality set.

The labeled set is intentionally small and original -- we never fabricate
hundreds of labels.  This tool validates the schema, reports per-kind counts,
per-kind label agreement (Cohen's kappa between annotators where labels
overlap) and the adjudication-resolution rate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

ALLOWED_KINDS = {
    "query_evidence_relevance",
    "question_jd_relevance",
    "question_answer_leakage",
    "judge_human_score",
    "followup_reasonableness",
    "report_evidential_support",
}
ALLOWED_LABELS = {0, 1, 2, 3, 4}


def validate(payload: dict) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    kinds = payload.get("kinds")
    if not isinstance(kinds, list) or set(kinds) != ALLOWED_KINDS:
        errors.append("kinds must list all six allowed kinds")
    annotator_review = payload.get("annotator_review") or {}
    if not annotator_review.get("annotators") or not annotator_review.get("reviewers"):
        errors.append("annotator_review needs annotators and reviewers")
    items = payload.get("items") or []
    if not items:
        errors.append("items must not be empty (original examples only, never fabricated volume)")
    seen: set[str] = set()
    for item in items:
        item_id = item.get("id")
        if not item_id or item_id in seen:
            errors.append(f"duplicate or missing id: {item_id}")
        seen.add(item_id)
        kind = item.get("kind")
        if kind not in ALLOWED_KINDS:
            errors.append(f"{item_id}: unknown kind {kind}")
        label = item.get("label")
        if label not in ALLOWED_LABELS:
            errors.append(f"{item_id}: label {label} out of range")
        if item.get("annotator") not in (annotator_review.get("annotators") or []):
            errors.append(f"{item_id}: unknown annotator")
        if item.get("reviewer") not in (annotator_review.get("reviewers") or []):
            errors.append(f"{item_id}: unknown reviewer")
        if item.get("disagreement") and not item.get("adjudicated"):
            errors.append(f"{item_id}: disagreement must be adjudicated")
        if item.get("adjudicated") and "final_label" not in item:
            errors.append(f"{item_id}: adjudicated item needs final_label")
    return errors


def cohens_kappa(pairs: list[tuple[int, int]]) -> float | None:
    """Cohen's kappa over (annotator_a, annotator_b) label pairs."""
    if len(pairs) < 2:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    from collections import Counter

    count_a = Counter(a for a, _ in pairs)
    count_b = Counter(b for _, b in pairs)
    expected = sum((count_a[label] / n) * (count_b[label] / n) for label in set(count_a) | set(count_b))
    if expected == 1:
        return None
    return round((observed - expected) / (1 - expected), 4)


def stats(payload: dict) -> dict:
    items = payload.get("items") or []
    per_kind: dict[str, int] = {}
    adjudicated = 0
    disagreements = 0
    for item in items:
        kind = item.get("kind")
        per_kind[kind] = per_kind.get(kind, 0) + 1
        if item.get("disagreement"):
            disagreements += 1
        if item.get("adjudicated"):
            adjudicated += 1
    pairs = [(item.get("label"), item.get("final_label")) for item in items if "final_label" in item and item.get("label") is not None]
    return {
        "total_items": len(items),
        "per_kind": per_kind,
        "disagreements": disagreements,
        "adjudicated": adjudicated,
        "adjudication_resolution_rate": round(adjudicated / len(items), 4) if items else 0.0,
        "annotator_vs_final_kappa": cohens_kappa(pairs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and summarize the labeled quality set.")
    parser.add_argument("--fixture", default="test/fixtures/cs_interview/labeled_quality.json")
    args = parser.parse_args()
    payload = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    errors = validate(payload)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 2
    result = stats(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("labeled quality set: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
