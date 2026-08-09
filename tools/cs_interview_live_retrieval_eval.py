"""Evaluate real RAGFlow retrieval over the reviewed CS interview datasets."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import requests


class LiveEvalError(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method, self.base_url + path, timeout=90, **kwargs)
        payload = response.json()
        if not response.ok or payload.get("code") != 0:
            raise LiveEvalError(
                f"{method} {path} failed: HTTP {response.status_code}, "
                f"code={payload.get('code')}, message={payload.get('message', '')}"
            )
        return payload

    def datasets_by_name(self) -> dict[str, dict[str, Any]]:
        rows = self.call("GET", "/datasets", params={"page": 1, "page_size": 100})["data"]
        return {row["name"]: row for row in rows}

    def retrieve(self, dataset_id: str, question: str) -> tuple[float, list[dict[str, Any]]]:
        start = time.perf_counter()
        payload = self.call(
            "POST",
            "/retrieval",
            json={
                "question": question,
                "dataset_ids": [dataset_id],
                "page": 1,
                "page_size": 5,
                "similarity_threshold": 0.15,
                "vector_similarity_weight": 0.3,
                "top_k": 128,
                "reference_metadata": {
                    "include": True,
                    "fields": ["question_id", "content_type", "role", "topic", "difficulty", "verified"],
                },
            },
        )["data"]
        latency_ms = (time.perf_counter() - start) * 1000
        return latency_ms, payload.get("chunks", [])


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def manifest_smoke_cases(manifest: dict[str, Any], manifest_path: Path) -> list[dict[str, Any]]:
    cases = []
    for dataset, spec in manifest["datasets"].items():
        for document in spec["documents"]:
            text = (manifest_path.parent / document["path"]).read_text(encoding="utf-8")
            match = re.search(r"^## (?:题目|问题)\s*$\s*(.+?)(?:\n\s*\n|\Z)", text, flags=re.MULTILINE | re.DOTALL)
            if not match:
                raise LiveEvalError(f"Cannot extract smoke query from {document['path']}")
            cases.append(
                {
                    "id": f"smoke-{document['metadata']['question_id']}",
                    "kind": "corpus_smoke",
                    "dataset": dataset,
                    "query": " ".join(match.group(1).split()),
                    "expected_question_id": document["metadata"]["question_id"],
                }
            )
    return cases


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="test/fixtures/cs_interview/public_eval/manifest.json")
    parser.add_argument("--cases", default="test/fixtures/cs_interview/public_eval/live_retrieval_eval.json")
    parser.add_argument("--base-url", default=os.getenv("RAGFLOW_BASE_URL", "http://localhost"))
    parser.add_argument("--api-key-env", default="RAGFLOW_API_KEY")
    parser.add_argument("--include-manifest-smoke", action="store_true", help="Add one direct retrieval check per manifest document.")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--fail-below-recall-at-3", type=float, default=0.85)
    parser.add_argument("--fail-below-hard-recall-at-3", type=float, default=0.8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key:
        raise LiveEvalError(f"Environment variable {args.api_key_env} is required")
    manifest_path = Path(args.manifest).resolve()
    manifest = load_json(manifest_path)
    cases = load_json(args.cases).get("cases", [])
    if args.include_manifest_smoke:
        cases = [*cases, *manifest_smoke_cases(manifest, manifest_path)]
    client = Client(args.base_url, api_key)
    remote_by_name = client.datasets_by_name()
    dataset_ids: dict[str, str] = {}
    for key, spec in manifest["datasets"].items():
        remote = remote_by_name.get(spec["name"])
        if not remote:
            raise LiveEvalError(f"Dataset not found: {spec['name']}")
        dataset_ids[key] = str(remote["id"])

    details: list[dict[str, Any]] = []
    latencies: list[float] = []
    reciprocal_ranks: list[float] = []
    hits_at_1 = 0
    hits_at_3 = 0
    hits_at_5 = 0
    for case in cases:
        latency_ms, chunks = client.retrieve(dataset_ids[case["dataset"]], case["query"])
        latencies.append(latency_ms)
        retrieved_ids = [str((chunk.get("document_metadata") or {}).get("question_id", "")) for chunk in chunks]
        expected = case["expected_question_id"]
        try:
            rank = retrieved_ids.index(expected) + 1
        except ValueError:
            rank = 0
        hits_at_1 += rank == 1
        hits_at_3 += 0 < rank <= 3
        hits_at_5 += 0 < rank <= 5
        reciprocal_ranks.append(1 / rank if rank else 0)
        top = chunks[0] if chunks else {}
        details.append(
            {
                "id": case["id"],
                "kind": case.get("kind", "clean"),
                "dataset": case["dataset"],
                "expected_question_id": expected,
                "rank": rank,
                "retrieved_question_ids": retrieved_ids,
                "top_similarity": round(float(top.get("similarity") or 0), 4),
                "latency_ms": round(latency_ms, 1),
            }
        )
    count = len(cases)
    metrics = {
        "cases": count,
        "recall_at_1": round(hits_at_1 / count, 4) if count else 0,
        "recall_at_3": round(hits_at_3 / count, 4) if count else 0,
        "recall_at_5": round(hits_at_5 / count, 4) if count else 0,
        "mrr": round(statistics.fmean(reciprocal_ranks), 4) if reciprocal_ranks else 0,
        "latency_p50_ms": round(percentile(latencies, 0.5), 1),
        "latency_p95_ms": round(percentile(latencies, 0.95), 1),
        "zero_result_cases": sum(not row["retrieved_question_ids"] for row in details),
    }

    by_kind: dict[str, dict[str, Any]] = {}
    for kind in sorted({row["kind"] for row in details}):
        rows = [row for row in details if row["kind"] == kind]
        by_kind[kind] = {
            "cases": len(rows),
            "recall_at_1": round(sum(row["rank"] == 1 for row in rows) / len(rows), 4),
            "recall_at_3": round(sum(0 < row["rank"] <= 3 for row in rows) / len(rows), 4),
            "mrr": round(statistics.fmean(1 / row["rank"] if row["rank"] else 0 for row in rows), 4),
            "latency_p95_ms": round(percentile([row["latency_ms"] for row in rows], 0.95), 1),
        }
    metrics["by_kind"] = by_kind
    hard_recall = by_kind.get("hard", {}).get("recall_at_3", 1.0)
    passed = (
        metrics["recall_at_3"] >= args.fail_below_recall_at_3
        and hard_recall >= args.fail_below_hard_recall_at_3
        and metrics["zero_result_cases"] == 0
    )
    output: dict[str, Any] = {"passed": passed, "metrics": metrics}
    if not args.summary_only:
        output["details"] = details
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if passed else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, requests.RequestException, LiveEvalError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc
