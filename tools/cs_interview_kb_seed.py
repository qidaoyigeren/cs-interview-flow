"""Create and populate the three CS interview datasets from a reviewed manifest.

The command is intentionally idempotent: documents are reused when their content
hash matches, and replaced when the local source changed. Authentication is read
from an environment variable so credentials never need to be committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

REQUIRED_METADATA = {
    "content_type",
    "role",
    "topic",
    "difficulty",
    "question_id",
    "source",
    "source_date",
    "quality_score",
    "verified",
    "license",
}
DATASET_CONTENT_TYPES = {
    "interview_experience": "interview_experience",
    "leetcode": "leetcode",
    "fundamentals": "fundamentals",
}


class SeedError(RuntimeError):
    pass


@dataclass
class SeededDataset:
    key: str
    id: str
    name: str
    documents: int
    parsed_documents: int
    chunks: int


class RAGFlowClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(
            method,
            self.base_url + path,
            timeout=kwargs.pop("timeout", self.timeout),
            **kwargs,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SeedError(f"{method} {path} returned non-JSON HTTP {response.status_code}") from exc
        if not response.ok or payload.get("code") != 0:
            raise SeedError(
                f"{method} {path} failed: HTTP {response.status_code}, "
                f"code={payload.get('code')}, message={payload.get('message', '')}"
            )
        return payload

    def list_datasets(self) -> list[dict[str, Any]]:
        # The RAGFlow list API treats an unknown exact `name` filter as a
        # permission error instead of an empty result, so filter client-side.
        return self.request("GET", "/datasets", params={"page": 1, "page_size": 100})["data"]

    def ensure_dataset(self, name: str, description: str, embedding_model: str) -> dict[str, Any]:
        exact = [row for row in self.list_datasets() if row.get("name") == name]
        if exact:
            return exact[0]
        return self.request(
            "POST",
            "/datasets",
            json={
                "name": name,
                "description": description,
                "embedding_model": embedding_model,
                "permission": "me",
                "chunk_method": "naive",
            },
        )["data"]

    def list_documents(self, dataset_id: str) -> list[dict[str, Any]]:
        return self.request(
            "GET",
            f"/datasets/{dataset_id}/documents",
            params={"page": 1, "page_size": 100, "orderby": "create_time", "desc": "true"},
        )["data"]["docs"]

    def delete_document(self, dataset_id: str, document_id: str) -> None:
        self.request("DELETE", f"/datasets/{dataset_id}/documents", json={"ids": [document_id]})

    def upload_document(self, dataset_id: str, path: Path) -> dict[str, Any]:
        with path.open("rb") as source:
            payload = self.request(
                "POST",
                f"/datasets/{dataset_id}/documents",
                files={"file": (path.name, source, "text/markdown")},
                timeout=120,
            )
        documents = payload["data"]
        if len(documents) != 1:
            raise SeedError(f"Expected one uploaded document for {path}, got {len(documents)}")
        return documents[0]

    def update_metadata(self, dataset_id: str, document_id: str, metadata: dict[str, Any]) -> None:
        self.request(
            "PATCH",
            f"/datasets/{dataset_id}/documents/{document_id}",
            json={"meta_fields": metadata},
        )

    def start_parse(self, dataset_id: str, document_ids: list[str]) -> None:
        if document_ids:
            self.request("POST", f"/datasets/{dataset_id}/chunks", json={"document_ids": document_ids})

    def document(self, dataset_id: str, document_id: str) -> dict[str, Any] | None:
        docs = self.request(
            "GET",
            f"/datasets/{dataset_id}/documents",
            params={"id": document_id, "page": 1, "page_size": 1},
        )["data"]["docs"]
        return docs[0] if docs else None

    def bind_interview_datasets(self, dataset_ids: dict[str, str]) -> dict[str, Any]:
        return self.request(
            "PUT",
            "/cs-interview/knowledge-config",
            json={
                "interview_experience_dataset_id": dataset_ids["interview_experience"],
                "leetcode_dataset_id": dataset_ids["leetcode"],
                "fundamentals_dataset_id": dataset_ids["fundamentals"],
                "enabled": True,
                "retrieval_config_snapshot": {
                    "similarity_threshold": 0.2,
                    "vector_similarity_weight": 0.3,
                    "top_n": 5,
                    "top_k": 128,
                    "rerank_id": "",
                },
            },
        )["data"]


def validate_manifest(manifest: dict[str, Any], root: Path) -> list[str]:
    errors: list[str] = []
    datasets = manifest.get("datasets")
    if not isinstance(datasets, dict):
        return ["manifest.datasets must be an object"]
    if set(datasets) != set(DATASET_CONTENT_TYPES):
        errors.append(f"datasets must be exactly {sorted(DATASET_CONTENT_TYPES)}")
    seen_question_ids: set[str] = set()
    for dataset_key, expected_content_type in DATASET_CONTENT_TYPES.items():
        dataset = datasets.get(dataset_key, {})
        documents = dataset.get("documents")
        if not isinstance(documents, list) or not documents:
            errors.append(f"{dataset_key}: documents must be a non-empty list")
            continue
        for index, document in enumerate(documents):
            label = f"{dataset_key}.documents[{index}]"
            relative_path = document.get("path")
            if not isinstance(relative_path, str) or not (root / relative_path).is_file():
                errors.append(f"{label}: missing document path {relative_path!r}")
            metadata = document.get("metadata")
            if not isinstance(metadata, dict):
                errors.append(f"{label}: metadata must be an object")
                continue
            missing = REQUIRED_METADATA - set(metadata)
            if missing:
                errors.append(f"{label}: missing metadata {sorted(missing)}")
            if metadata.get("content_type") != expected_content_type:
                errors.append(f"{label}: content_type must be {expected_content_type}")
            if metadata.get("difficulty") not in {"beginner", "medium", "advanced"}:
                errors.append(f"{label}: invalid difficulty")
            if metadata.get("verified") is not True:
                errors.append(f"{label}: verified must be true")
            try:
                quality_score = float(metadata.get("quality_score"))
                if not 0 <= quality_score <= 1:
                    raise ValueError
            except (TypeError, ValueError):
                errors.append(f"{label}: quality_score must be between 0 and 1")
            question_id = str(metadata.get("question_id", ""))
            if not question_id:
                errors.append(f"{label}: question_id must not be empty")
            elif question_id in seen_question_ids:
                errors.append(f"{label}: duplicate question_id {question_id}")
            seen_question_ids.add(question_id)
    return errors


def content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_for_parsing(
    client: RAGFlowClient,
    dataset_id: str,
    document_ids: list[str],
    timeout_seconds: int,
) -> tuple[int, int]:
    deadline = time.monotonic() + timeout_seconds
    pending = set(document_ids)
    parsed = 0
    chunks = 0
    while pending and time.monotonic() < deadline:
        for document_id in list(pending):
            row = client.document(dataset_id, document_id)
            if row is None:
                raise SeedError(f"Document disappeared while parsing: {document_id}")
            run = str(row.get("run", "")).upper()
            progress = float(row.get("progress") or 0)
            if run in {"FAIL", "CANCEL", "4", "5"}:
                raise SeedError(f"Document parse failed: {row.get('name')}: {row.get('progress_msg', '')}")
            if run == "DONE" or progress >= 1:
                pending.remove(document_id)
                parsed += 1
                chunks += int(row.get("chunk_count") or 0)
        if pending:
            time.sleep(2)
    if pending:
        raise SeedError(f"Timed out waiting for {len(pending)} documents to parse")
    return parsed, chunks


def seed_dataset(
    client: RAGFlowClient,
    manifest_root: Path,
    dataset_key: str,
    spec: dict[str, Any],
    embedding_model: str,
    parse_timeout: int,
) -> SeededDataset:
    dataset = client.ensure_dataset(spec["name"], spec.get("description", ""), embedding_model)
    dataset_id = str(dataset["id"])
    existing = {row["name"]: row for row in client.list_documents(dataset_id)}
    parse_ids: list[str] = []
    all_ids: list[str] = []
    for document_spec in spec["documents"]:
        path = manifest_root / document_spec["path"]
        digest = content_hash(path)
        metadata = {**document_spec["metadata"], "content_sha256": digest, "source_accessed_at": "2026-08-08"}
        current = existing.get(path.name)
        if current and (current.get("meta_fields") or {}).get("content_sha256") != digest:
            client.delete_document(dataset_id, str(current["id"]))
            current = None
        if current is None:
            current = client.upload_document(dataset_id, path)
            parse_ids.append(str(current["id"]))
        client.update_metadata(dataset_id, str(current["id"]), metadata)
        all_ids.append(str(current["id"]))
    client.start_parse(dataset_id, parse_ids)
    if parse_ids:
        wait_for_parsing(client, dataset_id, parse_ids, parse_timeout)
    final_documents = client.list_documents(dataset_id)
    selected = [row for row in final_documents if str(row.get("id")) in set(all_ids)]
    parsed_documents = sum(float(row.get("progress") or 0) >= 1 for row in selected)
    chunks = sum(int(row.get("chunk_count") or 0) for row in selected)
    return SeededDataset(
        key=dataset_key,
        id=dataset_id,
        name=spec["name"],
        documents=len(selected),
        parsed_documents=parsed_documents,
        chunks=chunks,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default="test/fixtures/cs_interview/public_eval/manifest.json",
        help="Reviewed corpus manifest.",
    )
    parser.add_argument("--base-url", default=os.getenv("RAGFLOW_BASE_URL", "http://localhost"))
    parser.add_argument("--api-key-env", default="RAGFLOW_API_KEY")
    parser.add_argument(
        "--embedding-model",
        default=os.getenv("CS_INTERVIEW_EMBEDDING_MODEL", "BAAI/bge-m3@cs-interview-eval@SILICONFLOW"),
    )
    parser.add_argument("--parse-timeout", type=int, default=900)
    parser.add_argument("--bind", action="store_true", help="Save the three datasets as the active interview knowledge config.")
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    with manifest_path.open(encoding="utf-8") as source:
        manifest = json.load(source)
    errors = validate_manifest(manifest, manifest_path.parent)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 2
    if args.validate_only:
        count = sum(len(spec["documents"]) for spec in manifest["datasets"].values())
        print(json.dumps({"valid": True, "documents": count}, ensure_ascii=False, indent=2))
        return 0
    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key:
        raise SeedError(f"Environment variable {args.api_key_env} is required")
    client = RAGFlowClient(args.base_url, api_key)
    results = [
        seed_dataset(
            client,
            manifest_path.parent,
            dataset_key,
            manifest["datasets"][dataset_key],
            args.embedding_model,
            args.parse_timeout,
        )
        for dataset_key in DATASET_CONTENT_TYPES
    ]
    output: dict[str, Any] = {
        "valid": True,
        "datasets": [result.__dict__ for result in results],
    }
    if args.bind:
        output["knowledge_config"] = client.bind_interview_datasets({result.key: result.id for result in results})
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, requests.RequestException, SeedError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc
