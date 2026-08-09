"""Client for the isolated CS interview code runner service."""

from __future__ import annotations

import os
from typing import Any, Protocol

from api.apps.services.cs_interview.domain import DomainError
from common.http_client import async_request


class CodeRunner(Protocol):
    async def execute(
        self,
        language: str,
        source_code: str,
        tests: list[dict[str, Any]],
        *,
        execution_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def health(self) -> bool: ...

    async def cancel(self, execution_id: str) -> bool: ...


class IsolatedCodeRunner:
    """HTTP client which never falls back to local or host execution."""

    def __init__(self, endpoint: str | None = None, timeout_seconds: int | None = None):
        self.endpoint = (endpoint or os.getenv("CS_INTERVIEW_RUNNER_URL", "http://cs-interview-runner:9390")).rstrip("/")
        self.timeout_seconds = timeout_seconds or int(os.getenv("CS_INTERVIEW_RUNNER_TIMEOUT_SECONDS", "8"))

    async def execute(
        self,
        language: str,
        source_code: str,
        tests: list[dict[str, Any]],
        *,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            response = await async_request(
                "POST",
                f"{self.endpoint}/v1/execute",
                json={
                    "execution_id": execution_id,
                    "language": language,
                    "source_code": source_code,
                    "tests": tests,
                    "limits": {
                        "wall_time_ms": self.timeout_seconds * 1000,
                        "cpu_time_ms": int(os.getenv("CS_INTERVIEW_RUNNER_CPU_MS", "3000")),
                        "memory_mb": int(os.getenv("CS_INTERVIEW_RUNNER_MEMORY_MB", "128")),
                        "processes": int(os.getenv("CS_INTERVIEW_RUNNER_PROCESSES", "16")),
                        "output_bytes": int(os.getenv("CS_INTERVIEW_RUNNER_OUTPUT_BYTES", "8192")),
                    },
                },
                request_timeout=self.timeout_seconds + 2,
                retries=0,
                follow_redirects=False,
            )
        except Exception as exc:
            raise DomainError("runner_unavailable", "The isolated code runner is unavailable.", http_status=503) from exc
        if response.status_code != 200:
            if response.status_code == 429:
                raise DomainError("runner_busy", "The isolated runner is at capacity.", http_status=503)
            if response.status_code >= 500:
                raise DomainError("runner_unavailable", "The isolated runner is temporarily unavailable.", http_status=503)
            raise DomainError("runner_error", f"The isolated runner rejected the execution ({response.status_code}).", http_status=409)
        result = response.json()
        if not isinstance(result, dict) or "status" not in result:
            raise DomainError("runner_error", "The isolated runner returned an invalid response.", http_status=502)
        return result

    async def health(self) -> bool:
        try:
            response = await async_request(
                "GET",
                f"{self.endpoint}/readyz",
                request_timeout=2,
                retries=0,
                follow_redirects=False,
            )
            return response.status_code == 200
        except Exception:  # noqa: BLE001 - a health probe must collapse transport/parser failures
            return False

    async def cancel(self, execution_id: str) -> bool:
        if not execution_id:
            return False
        try:
            response = await async_request(
                "DELETE",
                f"{self.endpoint}/v1/executions/{execution_id}",
                request_timeout=2,
                retries=0,
                follow_redirects=False,
            )
            return response.status_code in {200, 404}
        except Exception:  # noqa: BLE001 - worker cancellation is best-effort and rechecked from DB
            return False
