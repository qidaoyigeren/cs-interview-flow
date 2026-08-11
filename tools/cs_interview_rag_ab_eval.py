"""Run a paired real-RAGFlow retrieval A/B over interview-state queries."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import random
import statistics
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "test" / "fixtures" / "cs_interview" / "public_eval" / "manifest.json"
DEFAULT_CASES = REPOSITORY_ROOT / "test" / "fixtures" / "cs_interview" / "public_eval" / "rag_ab_cases.generated.json"
_THREAD_LOCAL = threading.local()
VARIANTS = ("raw_unfiltered", "raw_filtered", "state_unfiltered", "state_filtered")


class EvaluationError(RuntimeError):
    pass


def _load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def _case_fingerprint(case: dict[str, Any]) -> str:
    payload = {
        "id": case["id"],
        "query": case["query"],
        "expected_question_id": case["expected_question_id"],
        "state": case["state"],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _load_checkpoint(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvaluationError(f"Invalid checkpoint JSON at line {line_number}: {exc}") from exc
            if isinstance(row, dict) and row.get("id"):
                rows[str(row["id"])] = row
    return rows


def _compact_checkpoint(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as sink:
        for row in rows:
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


class Client:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def _session(self) -> requests.Session:
        session = getattr(_THREAD_LOCAL, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(self.headers)
            _THREAD_LOCAL.session = session
        return session

    def call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        last_error = "unknown request failure"
        for attempt in range(5):
            try:
                response = self._session().request(method, self.base_url + path, timeout=90, **kwargs)
                payload = response.json()
                if response.ok and payload.get("code") == 0:
                    return payload
                message = str(payload.get("message", ""))
                last_error = f"HTTP {response.status_code}, code={payload.get('code')}, message={message}"
                retryable = response.status_code >= 500 or (payload.get("code") == 100 and "Embedding" in message)
                if not retryable:
                    break
            except (requests.RequestException, ValueError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                _THREAD_LOCAL.session = None
            if attempt < 4:
                time.sleep(min(2**attempt, 8))
        raise EvaluationError(f"{method} {path} failed after bounded retries: {last_error}")

    def datasets_by_name(self) -> dict[str, dict[str, Any]]:
        rows = self.call("GET", "/datasets", params={"page": 1, "page_size": 100})["data"]
        return {row["name"]: row for row in rows}

    def retrieve(self, dataset_id: str, query: str, metadata_condition: dict[str, Any] | None) -> tuple[float, list[dict[str, Any]]]:
        request = {
            "question": query,
            "dataset_ids": [dataset_id],
            "page": 1,
            "page_size": 5,
            "similarity_threshold": 0.15,
            "vector_similarity_weight": 0.3,
            "top_k": 128,
            "reference_metadata": {
                "include": True,
                "fields": ["question_id", "content_type", "role", "topic", "difficulty", "verified", "quality_score"],
            },
        }
        if metadata_condition:
            request["metadata_condition"] = metadata_condition
        started = time.perf_counter()
        payload = self.call("POST", "/retrieval", json=request)["data"]
        return (time.perf_counter() - started) * 1000, list(payload.get("chunks", []))


def _candidate_query(case: dict[str, Any]) -> str:
    state = case["state"]
    return (
        f"role={state['role']}; topic_id={state['topic']}; difficulty={state['difficulty']}; "
        f"planner_action={state['planner_action']}; weak_points={case['query']}"
    )


def _metadata_condition(case: dict[str, Any]) -> dict[str, Any]:
    state = case["state"]
    return {
        "logic": "and",
        "conditions": [
            {"name": "content_type", "comparison_operator": "=", "value": state["content_type"]},
            {"name": "role", "comparison_operator": "=", "value": state["role"]},
            {"name": "topic", "comparison_operator": "=", "value": state["topic"]},
            {"name": "difficulty", "comparison_operator": "=", "value": state["difficulty"]},
            {"name": "verified", "comparison_operator": "=", "value": True},
            {"name": "quality_score", "comparison_operator": ">=", "value": 0.6},
        ],
    }


def _rank(chunks: list[dict[str, Any]], expected: str) -> tuple[int, list[str]]:
    retrieved = [str((chunk.get("document_metadata") or {}).get("question_id") or "") for chunk in chunks]
    try:
        return retrieved.index(expected) + 1, retrieved
    except ValueError:
        return 0, retrieved


def _run_variant(client: Client, dataset_id: str, case: dict[str, Any], variant: str) -> dict[str, Any]:
    if variant not in VARIANTS:
        raise EvaluationError(f"Unknown evaluation variant: {variant}")
    query = _candidate_query(case) if variant.startswith("state_") else str(case["query"])
    metadata_condition = _metadata_condition(case) if variant.endswith("_filtered") else None
    latency_ms, chunks = client.retrieve(dataset_id, query, metadata_condition)
    rank, retrieved = _rank(chunks, str(case["expected_question_id"]))
    return {
        "variant": variant,
        "rank": rank,
        "retrieved_question_ids": retrieved,
        "latency_ms": round(latency_ms, 1),
        "zero_result": not chunks,
    }


def _evaluate_case(client: Client, dataset_ids: dict[str, str], case: dict[str, Any]) -> dict[str, Any]:
    offset = int(hashlib.sha256(str(case["id"]).encode()).hexdigest()[:2], 16) % len(VARIANTS)
    order = VARIANTS[offset:] + VARIANTS[:offset]
    results = {}
    for variant in order:
        try:
            results[variant] = _run_variant(client, dataset_ids[case["dataset"]], case, variant)
        except EvaluationError as exc:
            raise EvaluationError(f"case={case['id']} variant={variant}: {exc}") from exc
    return {
        "id": case["id"],
        "case_fingerprint": _case_fingerprint(case),
        "kind": case["kind"],
        "dataset": case["dataset"],
        "expected_question_id": case["expected_question_id"],
        "review_status": case.get("review_status", "unknown"),
        **{variant: results[variant] for variant in VARIANTS},
    }


def _variant_metrics(details: list[dict[str, Any]], variant: str) -> dict[str, Any]:
    rows = [row[variant] for row in details]
    count = len(rows)
    return {
        "cases": count,
        "recall_at_1": round(sum(row["rank"] == 1 for row in rows) / count, 4),
        "recall_at_3": round(sum(0 < row["rank"] <= 3 for row in rows) / count, 4),
        "recall_at_5": round(sum(0 < row["rank"] <= 5 for row in rows) / count, 4),
        "mrr": round(statistics.fmean(1 / row["rank"] if row["rank"] else 0 for row in rows), 4),
        "latency_p50_ms": round(_percentile([row["latency_ms"] for row in rows], 0.5), 1),
        "latency_p95_ms": round(_percentile([row["latency_ms"] for row in rows], 0.95), 1),
        "zero_result_cases": sum(row["zero_result"] for row in rows),
    }


def _mcnemar_exact(improved: int, regressed: int) -> float:
    discordant = improved + regressed
    if not discordant:
        return 1.0
    lower = min(improved, regressed)
    probability = 2 * sum(math.comb(discordant, k) for k in range(lower + 1)) / (2**discordant)
    return min(1.0, probability)


def _cluster_bootstrap(details: list[dict[str, Any]], baseline: str, candidate: str, k: int, iterations: int, seed: int) -> list[float]:
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in details:
        clusters[str(row["expected_question_id"])].append(row)
    cluster_ids = sorted(clusters)
    rng = random.Random(seed)
    deltas: list[float] = []
    for _ in range(iterations):
        sample = [row for _cluster in rng.choices(cluster_ids, k=len(cluster_ids)) for row in clusters[_cluster]]
        baseline_recall = sum(0 < row[baseline]["rank"] <= k for row in sample) / len(sample)
        candidate_recall = sum(0 < row[candidate]["rank"] <= k for row in sample) / len(sample)
        deltas.append(candidate_recall - baseline_recall)
    return deltas


def _paired_metrics(details: list[dict[str, Any]], baseline: str, candidate: str, iterations: int, seed: int) -> dict[str, Any]:
    baseline_metrics = _variant_metrics(details, baseline)
    candidate_metrics = _variant_metrics(details, candidate)
    paired = {}
    confidence_intervals = {}
    for k in (1, 3):
        improved = sum(not (0 < row[baseline]["rank"] <= k) and 0 < row[candidate]["rank"] <= k for row in details)
        regressed = sum(0 < row[baseline]["rank"] <= k and not (0 < row[candidate]["rank"] <= k) for row in details)
        paired[f"recall_at_{k}"] = {
            "improved_cases": improved,
            "regressed_cases": regressed,
            "mcnemar_exact_p": round(_mcnemar_exact(improved, regressed), 6),
        }
        deltas = _cluster_bootstrap(details, baseline, candidate, k, iterations, seed)
        confidence_intervals[f"recall_at_{k}_delta"] = [
            round(_percentile(deltas, 0.025), 4),
            round(_percentile(deltas, 0.975), 4),
        ]
    return {
        "baseline": baseline,
        "candidate": candidate,
        "recall_at_1_delta": round(candidate_metrics["recall_at_1"] - baseline_metrics["recall_at_1"], 4),
        "recall_at_3_delta": round(candidate_metrics["recall_at_3"] - baseline_metrics["recall_at_3"], 4),
        "mrr_delta": round(candidate_metrics["mrr"] - baseline_metrics["mrr"], 4),
        "paired": paired,
        "cluster_bootstrap_95_ci": confidence_intervals,
        "cluster_count": len({str(row["expected_question_id"]) for row in details}),
    }


def _by_kind(details: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for kind in sorted({str(row["kind"]) for row in details}):
        rows = [row for row in details if row["kind"] == kind]
        result[kind] = {
            "cases": len(rows),
            "raw_unfiltered_recall_at_3": _variant_metrics(rows, "raw_unfiltered")["recall_at_3"],
            "state_filtered_recall_at_3": _variant_metrics(rows, "state_filtered")["recall_at_3"],
        }
        result[kind]["delta"] = round(result[kind]["state_filtered_recall_at_3"] - result[kind]["raw_unfiltered_recall_at_3"], 4)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--base-url", default=os.getenv("RAGFLOW_BASE_URL", "http://localhost"))
    parser.add_argument("--api-key-env", default="RAGFLOW_API_KEY")
    parser.add_argument("--output")
    parser.add_argument("--checkpoint", help="JSONL case-result checkpoint; defaults next to --output.")
    parser.add_argument("--no-resume", action="store_true", help="Ignore an existing checkpoint.")
    parser.add_argument("--concurrency", type=int, default=4, choices=range(1, 9))
    parser.add_argument("--bootstrap-iterations", type=int, default=2_000)
    parser.add_argument("--seed", type=int, default=20260810)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--summary-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key:
        raise EvaluationError(f"Environment variable {args.api_key_env} is required")
    manifest = _load_json(args.manifest)
    payload = _load_json(args.cases)
    cases = list(payload.get("cases") or [])
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        raise EvaluationError("No A/B cases were provided")
    client = Client(args.base_url, api_key)
    remote = client.datasets_by_name()
    dataset_ids: dict[str, str] = {}
    for key, spec in manifest["datasets"].items():
        dataset = remote.get(spec["name"])
        if not dataset:
            raise EvaluationError(f"Dataset not found: {spec['name']}")
        dataset_ids[key] = str(dataset["id"])
    checkpoint_path = Path(args.checkpoint).resolve() if args.checkpoint else None
    if checkpoint_path is None and args.output:
        checkpoint_path = Path(str(Path(args.output).resolve()) + ".checkpoint.jsonl")
    checkpoint = {} if args.no_resume else _load_checkpoint(checkpoint_path)
    details_by_id = {
        str(case["id"]): checkpoint[str(case["id"])]
        for case in cases
        if str(case["id"]) in checkpoint and checkpoint[str(case["id"])].get("case_fingerprint") == _case_fingerprint(case)
    }
    pending = [case for case in cases if str(case["id"]) not in details_by_id]
    if checkpoint_path:
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    first_error: Exception | None = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {executor.submit(_evaluate_case, client, dataset_ids, case): case for case in pending}
        for future in concurrent.futures.as_completed(futures):
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001 - finish and checkpoint other independent cases first
                if first_error is None:
                    first_error = exc
                continue
            details_by_id[str(row["id"])] = row
            if checkpoint_path:
                with checkpoint_path.open("a", encoding="utf-8") as sink:
                    sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                    sink.flush()
    if first_error is not None:
        raise first_error
    details = [details_by_id[str(case["id"])] for case in cases]
    if checkpoint_path:
        _compact_checkpoint(checkpoint_path, details)
    review_statuses = sorted({str(row["review_status"]) for row in details})
    result: dict[str, Any] = {
        "version": "cs-interview-real-retrieval-ab-v1",
        "variant_definitions": {
            "raw_unfiltered": "Raw interview query without metadata constraints.",
            "raw_filtered": "Raw interview query with role/topic/difficulty/quality metadata constraints.",
            "state_unfiltered": "Structured planner/state query without metadata constraints.",
            "state_filtered": "Structured planner/state query with role/topic/difficulty/quality metadata constraints.",
        },
        "sample": {
            "cases": len(details),
            "source_documents": len({str(row["expected_question_id"]) for row in details}),
            "resumed_cases": len(cases) - len(pending),
            "review_statuses": review_statuses,
            "resume_eligible": review_statuses == ["reviewed"],
        },
        "variants": {variant: _variant_metrics(details, variant) for variant in VARIANTS},
        "comparisons": {
            "full_vs_baseline": _paired_metrics(details, "raw_unfiltered", "state_filtered", args.bootstrap_iterations, args.seed),
            "filter_only": _paired_metrics(details, "raw_unfiltered", "raw_filtered", args.bootstrap_iterations, args.seed),
            "state_query_only": _paired_metrics(details, "raw_unfiltered", "state_unfiltered", args.bootstrap_iterations, args.seed),
        },
        "by_kind": _by_kind(details),
    }
    if not args.summary_only:
        result["details"] = details
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result if not args.summary_only else {key: value for key, value in result.items() if key != "details"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, requests.RequestException, EvaluationError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc
