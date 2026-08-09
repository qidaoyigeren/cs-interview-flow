"""Unified, versioned trace events for the CS interview pipeline.

This module is the single owning abstraction for lifecycle tracing.  Every
service emits through :class:`TraceEmitter` instead of hand-rolling ad-hoc
log dictionaries, and every event shares the same ``trace_id`` / ``session_id``
/ ``round_id`` so logs, metrics and traces correlate.

Privacy contract (enforced in code, asserted by tests):

* Events never contain full JD / resume / answer / code / reference answers /
  hidden tests or model credentials.  Only ids, hashes, versions, numeric
  metrics and allow-listed structured reasons are stored.
* A failing trace write must never break the business transaction: ``flush``
  is best-effort, swallows errors, and only bumps a failure counter.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from api.apps.services.cs_interview.observability import TRACE_EVENT_WRITE_FAILURE, operation_context
from api.db.db_models import DB, InterviewTraceEvent

LOGGER = logging.getLogger("api.apps.services.cs_interview.tracing")

EVENT_VERSION = "v1"
_REPLAY_TRACE_PREFIX = "replay:"


class TraceEventKind(StrEnum):
    SESSION_CREATED = "session_created"
    JOB_EXTRACTED = "job_extracted"
    RESUME_EXTRACTED = "resume_extracted"
    PLANNER_ACTION_SELECTED = "planner_action_selected"
    RETRIEVAL_STARTED = "retrieval_started"
    RETRIEVAL_COMPLETED = "retrieval_completed"
    EVIDENCE_REJECTED = "evidence_rejected"
    QUESTION_GENERATED = "question_generated"
    QUESTION_REJECTED = "question_rejected"
    ANSWER_RECEIVED = "answer_received"
    ANSWER_STATE_EXTRACTED = "answer_state_extracted"
    JUDGE_COMPLETED = "judge_completed"
    FOLLOWUP_SELECTED = "followup_selected"
    CODE_EXECUTION_COMPLETED = "code_execution_completed"
    REPORT_GENERATED = "report_generated"
    SESSION_COMPLETED = "session_completed"
    SESSION_FAILED = "session_failed"
    SESSION_REPLAYED = "session_replayed"
    USER_FEEDBACK_RECEIVED = "user_feedback_received"
    MODEL_CALL_COMPLETED = "model_call_completed"
    MODEL_CALL_FAILED = "model_call_failed"


# Keys that may flow into trace metadata verbatim (structured reasons and
# enums only -- never candidate/job content).
_TRACE_ALLOWED_EXACT = frozenset(
    {
        "category",
        "deduplicated",
        "difficulty",
        "error_class",
        "error_code",
        "kind",
        "model",
        "planner_action",
        "question_type",
        "reason",
        "reason_branch",
        "result",
        "selected_action",
        "stage",
        "status",
        "retryable",
        "covered",
        "uncovered",
    }
)

# Sensitive substrings: any metadata key containing one of these is dropped.
_TRACE_UNSAFE_SUBSTRINGS = (
    "answer",
    "api_key",
    "authorization",
    "claim_fact",
    "code_spec",
    "content",
    "credential",
    "feedback",
    "focus",
    "password",
    "prompt",
    "reference",
    "refresh_token",
    "rubric",
    "secret",
    "source_text",
    "statement",
    "summary",
    "test",
    "access_token",
    "token_value",
    "user_input",
)


def _trace_safe_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _TRACE_ALLOWED_EXACT:
        return True
    # Suffix-based allow for identifiers and numeric metrics before the
    # substring deny, so e.g. test_count stays allowed while hidden_tests is
    # dropped.
    if lowered.endswith(
        ("_id", "_count", "_hash", "_version", "_ms", "_seconds", "_ratio", "_score", "_cost", "_at")
    ):
        return True
    if lowered in {"score", "sequence"}:
        return True
    return not any(substring in lowered for substring in _TRACE_UNSAFE_SUBSTRINGS)


def _trace_safe_value(value: Any, *, max_chars: int = 300) -> Any:
    if isinstance(value, str):
        return value[:max_chars]
    if isinstance(value, dict):
        return {key: _trace_safe_value(item, max_chars=max_chars) for key, item in value.items() if _trace_safe_key(key)}
    if isinstance(value, (list, tuple)):
        return [_trace_safe_value(item, max_chars=max_chars) for item in value][:50]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:max_chars]


def _trace_safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Allow-list metadata so no candidate/job content or credentials leak."""
    if not isinstance(metadata, dict):
        return {}
    return {str(key): _trace_safe_value(value) for key, value in metadata.items() if _trace_safe_key(str(key))}


def resolve_trace_id(*, operation_id: str | None, request_id: str | None, session_id: str | None, replay: bool = False) -> str:
    """Correlate trace events with a stable trace id."""
    if replay:
        return f"{_REPLAY_TRACE_PREFIX}{session_id or ''}"
    if operation_id:
        return f"op-{operation_id}"
    if request_id:
        return f"req-{request_id}"
    return f"sess-{session_id or ''}"


@dataclass(frozen=True)
class TraceEvent:
    event_type: str
    session_id: str
    tenant_id: str
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = ""
    round_id: str | None = None
    request_id: str | None = None
    operation_id: str | None = None
    event_version: str = EVENT_VERSION
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: int | None = None
    status: str = "succeeded"
    error_code: str | None = None
    planner_version: str = ""
    prompt_version: str = ""
    model_snapshot: dict[str, Any] = field(default_factory=dict)
    knowledge_base_versions: dict[str, Any] = field(default_factory=dict)
    job_extraction_version: str | None = None
    resume_extraction_version: str | None = None
    input_token_count: int = 0
    output_token_count: int = 0
    estimated_cost: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.event_id,
            "trace_id": self.trace_id,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "round_id": self.round_id,
            "request_id": self.request_id,
            "operation_id": self.operation_id,
            "tenant_id": self.tenant_id,
            "event_type": self.event_type,
            "event_version": self.event_version,
            "occurred_at": self.occurred_at,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_code": self.error_code,
            "planner_version": self.planner_version,
            "prompt_version": self.prompt_version,
            "model_snapshot": self.model_snapshot,
            "knowledge_base_versions": self.knowledge_base_versions,
            "job_extraction_version": self.job_extraction_version,
            "resume_extraction_version": self.resume_extraction_version,
            "input_token_count": self.input_token_count,
            "output_token_count": self.output_token_count,
            "estimated_cost": self.estimated_cost,
            "metadata": self.metadata,
        }


class TraceEmitter:
    """In-memory buffer of trace events flushed best-effort to the DB.

    ``emit`` only appends to memory and never raises; ``flush`` runs in its own
    transaction and swallows every failure (counter + log), so tracing can never
    break the main business transaction.
    """

    def __init__(self, *, max_buffered: int = 200):
        self._buffer: list[TraceEvent] = []
        self._max_buffered = max_buffered

    def emit(
        self,
        event_type: str,
        *,
        session_id: str | None = None,
        round_id: str | None = None,
        request_id: str | None = None,
        operation_id: str | None = None,
        tenant_id: str | None = None,
        status: str = "succeeded",
        duration_ms: int | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
        model_snapshot: dict[str, Any] | None = None,
        kb_versions: dict[str, Any] | None = None,
        prompt_version: str | None = None,
        planner_version: str | None = None,
        job_extraction_version: str | None = None,
        resume_extraction_version: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost: float | None = None,
        replay: bool = False,
        immediate: bool = False,
    ) -> None:
        context = operation_context.get()
        resolved_session = session_id or (context.session_id if context else None) or ""
        resolved_tenant = tenant_id or (context.tenant_id if context else None) or ""
        resolved_request = request_id or (context.request_id if context else None)
        resolved_operation = operation_id or (context.operation_id if context else None)
        resolved_round = round_id or (context.round_id if context else None)
        trace_id = resolve_trace_id(
            operation_id=resolved_operation,
            request_id=resolved_request,
            session_id=resolved_session,
            replay=replay,
        )
        event = TraceEvent(
            event_type=str(event_type),
            session_id=resolved_session,
            tenant_id=resolved_tenant,
            trace_id=trace_id,
            round_id=resolved_round,
            request_id=resolved_request,
            operation_id=resolved_operation,
            status=status,
            duration_ms=duration_ms,
            error_code=error_code,
            metadata=_trace_safe_metadata(metadata),
            model_snapshot=_trace_safe_value(dict(model_snapshot or {})),
            knowledge_base_versions=_trace_safe_value(dict(kb_versions or {})),
            prompt_version=prompt_version or (context.prompt_version if context else "") or "",
            planner_version=planner_version or (context.planner_version if context else "") or "",
            job_extraction_version=job_extraction_version,
            resume_extraction_version=resume_extraction_version,
            input_token_count=int(input_tokens or 0),
            output_token_count=int(output_tokens or 0),
            estimated_cost=estimated_cost,
        )
        self._buffer.append(event)
        if immediate or len(self._buffer) >= self._max_buffered:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        pending, self._buffer = self._buffer, []
        try:
            with DB.atomic():
                InterviewTraceEvent.insert_many([event.to_row() for event in pending]).execute()
        except Exception:
            # Never break the business transaction because tracing failed.
            TRACE_EVENT_WRITE_FAILURE.add(1)
            LOGGER.exception("CS interview trace event flush failed", extra={"trace_events": len(pending)})

    def clear(self) -> None:
        self._buffer.clear()

    @property
    def buffered(self) -> int:
        return len(self._buffer)


# Module-level emitter shared by the whole pipeline. Workers flush at operation
# boundaries; direct API paths request an immediate best-effort flush.
TRACE_EMITTER = TraceEmitter()
