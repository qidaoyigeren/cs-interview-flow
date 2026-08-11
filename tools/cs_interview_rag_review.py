"""Human review of the generated RAG retrieval challenge cases.

The 500 cases in ``rag_ab_cases.generated.json`` are model-assisted candidates
flagged ``model_generated_unreviewed``. This tool applies reviewer decisions
(from a JSONL review file) to each case, records the reviewer id and status, and
only flips the aggregate ``resume_eligible`` flag once the human review ratio
reaches the configured threshold. It never fabricates review decisions and never
marks the set resume-eligible from a partial review.

Review file format (one JSON object per line):

    {"id": "public-go-leak-001-paraphrase", "reviewer_id": "alice",
     "status": "approved", "note": "answerable and leakage-free"}
    {"id": "public-go-leak-001-scenario", "reviewer_id": "alice",
     "status": "rejected", "note": "not answerable from source"}

Only ``approved`` counts toward the reviewed ratio.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = REPOSITORY_ROOT / "test" / "fixtures" / "cs_interview" / "public_eval" / "rag_ab_cases.generated.json"
DEFAULT_RESULTS = REPOSITORY_ROOT / "test" / "fixtures" / "cs_interview" / "public_eval" / "rag_ab_results.generated.json"
REQUIRED_REVIEW_RATIO = 0.8


def load_reviews(path: Path | str) -> dict[str, dict[str, Any]]:
    path = Path(path)
    reviews: dict[str, dict[str, Any]] = {}
    if not path.exists():
        raise FileNotFoundError(f"review file not found: {path}")
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid review JSON at line {line_number}: {exc}") from exc
            if not isinstance(row, dict) or not str(row.get("id") or "").strip():
                raise ValueError(f"review line {line_number} must contain an id")
            reviewer_id = str(row.get("reviewer_id") or "").strip()
            if not reviewer_id:
                raise ValueError(f"review line {line_number} must contain reviewer_id")
            status = str(row.get("status") or "").strip()
            if status not in {"approved", "rejected"}:
                raise ValueError(f"review line {line_number} status must be approved|rejected")
            reviews[str(row["id"])] = {
                "id": str(row["id"]),
                "reviewer_id": reviewer_id,
                "status": status,
                "note": str(row.get("note") or "")[:500],
            }
    return reviews


def apply_reviews(cases: list[dict[str, Any]], reviews: dict[str, dict[str, Any]], *, required_ratio: float = REQUIRED_REVIEW_RATIO) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    unknown_ids = sorted(set(reviews) - {str(item.get("id")) for item in cases})
    if unknown_ids:
        raise ValueError(f"review refers to unknown case ids: {', '.join(unknown_ids[:5])}")
    applied = 0
    approved = 0
    updated: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id") or "")
        review = reviews.get(case_id)
        if review is None:
            updated.append(case)
            continue
        applied += 1
        approved += int(review["status"] == "approved")
        case = {**case, "reviewer": review["reviewer_id"], "review_status": "human_approved" if review["status"] == "approved" else "human_rejected", "review_note": review["note"]}
        updated.append(case)
    total = len(cases)
    reviewed_ratio = round(applied / total, 4) if total else 0.0
    approved_ratio = round(approved / total, 4) if total else 0.0
    resume_eligible = bool(total and approved_ratio >= required_ratio and applied == total)
    labeling = {
        "status": "human_reviewed" if applied == total else "partially_reviewed",
        "reviewed_count": applied,
        "total_count": total,
        "approved_count": approved,
        "reviewed_ratio": reviewed_ratio,
        "approved_ratio": approved_ratio,
        "resume_eligible": resume_eligible,
        "required_review_ratio": required_ratio,
    }
    return updated, labeling


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_file", help="JSONL review file (one decision per line)")
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--write", action="store_true", help="Write updated cases and results back to disk")
    parser.add_argument("--ratio", type=float, default=REQUIRED_REVIEW_RATIO, help="approved ratio required for resume_eligible")
    args = parser.parse_args()

    with Path(args.cases).open(encoding="utf-8") as source:
        payload = json.load(source)
    cases = payload.get("cases") or []
    if not cases:
        print("no cases found", file=sys.stderr)
        return 1
    reviews = load_reviews(Path(args.review_file))
    updated, labeling = apply_reviews(cases, reviews, required_ratio=args.ratio)
    payload["labeling"] = labeling
    print(
        f"reviewed {labeling['reviewed_count']}/{labeling['total_count']} "
        f"approved_ratio={labeling['approved_ratio']} resume_eligible={labeling['resume_eligible']}"
    )
    if not args.write:
        return 0
    payload["cases"] = updated
    with Path(args.cases).open("w", encoding="utf-8", newline="\n") as sink:
        json.dump(payload, sink, ensure_ascii=False, indent=2)
    results_path = Path(args.results)
    if results_path.exists():
        with results_path.open(encoding="utf-8") as source:
            results = json.load(source)
        sample = results.get("sample") or {}
        sample["review_statuses"] = list(dict.fromkeys(str(item.get("review_status")) for item in updated))
        sample["reviewed_count"] = labeling["reviewed_count"]
        sample["resume_eligible"] = labeling["resume_eligible"]
        results["sample"] = sample
        with results_path.open("w", encoding="utf-8", newline="\n") as sink:
            json.dump(results, sink, ensure_ascii=False, indent=2)
    print(f"wrote {args.cases}" + (f" and {results_path}" if results_path.exists() else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
