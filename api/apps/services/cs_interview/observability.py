"""Low-cardinality telemetry and safe correlation context."""

from __future__ import annotations

import contextvars
import hashlib
from dataclasses import dataclass
from typing import Any

try:
    from opentelemetry import metrics, trace
except ImportError:  # pragma: no cover - production dependencies include OTel
    metrics = None
    trace = None


@dataclass(frozen=True)
class OperationContext:
    tenant_id: str
    user_id: str
    session_id: str
    operation_id: str
    request_id: str
    lease_owner: str = ""
    round_id: str | None = None
    stage: str = "dispatch"
    prompt_version: str = ""
    planner_version: str = ""
    knowledge_snapshot_version: str = ""
    runtime_config: dict[str, Any] | None = None


operation_context: contextvars.ContextVar[OperationContext | None] = contextvars.ContextVar(
    "cs_interview_operation_context", default=None
)


METRIC_ATTRIBUTE_KEYS = frozenset({"operation_type", "stage", "status", "error_code", "model", "event_type", "language", "result"})
SAFE_LOG_VALUE_KEYS = frozenset(
    {
        "attempt_count",
        "error_class",
        "error_code",
        "event_sequence",
        "latency_ms",
        "model",
        "operation_type",
        "stage",
        "status",
    }
)


class _NoopInstrument:
    def add(self, *_args, **_kwargs) -> None:
        return None

    def record(self, *_args, **_kwargs) -> None:
        return None


def _instrument(kind: str, name: str, *, unit: str = "1"):
    if metrics is None:
        return _NoopInstrument()
    meter = metrics.get_meter("ragflow.cs_interview")
    return getattr(meter, kind)(name, unit=unit)


OPERATION_DURATION = _instrument("create_histogram", "cs_interview.operation_duration_seconds", unit="s")
OPERATION_QUEUE_DELAY = _instrument("create_histogram", "cs_interview.operation_queue_delay_seconds", unit="s")
OPERATION_RETRY = _instrument("create_counter", "cs_interview.operation_retry_total")
OPERATION_STUCK = _instrument("create_counter", "cs_interview.operation_stuck_total")
LLM_REQUEST = _instrument("create_counter", "cs_interview.llm_request_total")
LLM_LATENCY = _instrument("create_histogram", "cs_interview.llm_latency_seconds", unit="s")
LLM_TOKEN = _instrument("create_counter", "cs_interview.llm_token_total", unit="token")
LLM_ESTIMATED_COST = _instrument("create_counter", "cs_interview.llm_estimated_cost", unit="USD")
RETRIEVAL_LATENCY = _instrument("create_histogram", "cs_interview.retrieval_latency_seconds", unit="s")
RETRIEVAL_ZERO_RESULT = _instrument("create_counter", "cs_interview.retrieval_zero_result_total")
QUESTION_GENERATION_FAILURE = _instrument("create_counter", "cs_interview.question_generation_failure_total")
JUDGE_LOW_CONFIDENCE = _instrument("create_counter", "cs_interview.judge_low_confidence_total")
SSE_RECONNECT = _instrument("create_counter", "cs_interview.sse_reconnect_total")
SSE_ACTIVE = _instrument("create_up_down_counter", "cs_interview.sse_active_connections")
SESSION_COMPLETION = _instrument("create_counter", "cs_interview.session_completion_total")
SESSION_FAILURE = _instrument("create_counter", "cs_interview.session_failure_total")
RUNNER_EXECUTION = _instrument("create_counter", "cs_interview.runner_execution_total")
RUNNER_TIMEOUT = _instrument("create_counter", "cs_interview.runner_timeout_total")
TRACE_EVENT_WRITE_FAILURE = _instrument("create_counter", "cs_interview.trace_event_write_failure_total")
STAGE_LATENCY = _instrument("create_histogram", "cs_interview.stage_latency_seconds", unit="s")


def metric_attributes(**values: str | None) -> dict[str, str]:
    return {key: str(value)[:128] for key, value in values.items() if key in METRIC_ATTRIBUTE_KEYS and value is not None}


def safe_log_context(context: OperationContext, **values: Any) -> dict[str, Any]:
    return {
        "tenant_id": context.tenant_id,
        "user_id_hash": hashlib.sha256(context.user_id.encode("utf-8")).hexdigest(),
        "session_id": context.session_id,
        "round_id": context.round_id,
        "operation_id": context.operation_id,
        "request_id": context.request_id,
        "prompt_version": context.prompt_version,
        "planner_version": context.planner_version,
        "knowledge_snapshot_version": context.knowledge_snapshot_version,
        **{key: value for key, value in values.items() if key in SAFE_LOG_VALUE_KEYS},
    }


def tracer():
    return trace.get_tracer("ragflow.cs_interview") if trace is not None else None
