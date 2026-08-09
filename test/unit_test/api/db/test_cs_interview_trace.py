"""Trace event privacy, buffering and best-effort flush tests."""

from __future__ import annotations

import pytest
from peewee import SqliteDatabase

from api.apps.services.cs_interview.observability import OperationContext, operation_context
from api.apps.services.cs_interview.tracing import (
    TRACE_EMITTER,
    TraceEmitter,
    TraceEventKind,
    _trace_safe_metadata,
    resolve_trace_id,
)
from api.db.db_models import (
    CodeSubmission,
    InterviewAuditLog,
    InterviewDeletionRequest,
    InterviewEvent,
    InterviewJob,
    InterviewKnowledgeConfig,
    InterviewModelCall,
    InterviewOperation,
    InterviewOperationCheckpoint,
    InterviewProfile,
    InterviewReport,
    InterviewRequest,
    InterviewResume,
    InterviewRound,
    InterviewSession,
    InterviewTraceEvent,
)

MODELS = [
    InterviewJob,
    InterviewProfile,
    InterviewResume,
    InterviewKnowledgeConfig,
    InterviewSession,
    InterviewRound,
    InterviewReport,
    CodeSubmission,
    InterviewRequest,
    InterviewOperation,
    InterviewEvent,
    InterviewOperationCheckpoint,
    InterviewModelCall,
    InterviewDeletionRequest,
    InterviewAuditLog,
    InterviewTraceEvent,
]


@pytest.fixture
def trace_db(tmp_path, monkeypatch):
    database = SqliteDatabase(tmp_path / "trace.sqlite")
    with database.bind_ctx(MODELS, bind_refs=False, bind_backrefs=False):
        database.create_tables(MODELS)
        from api.apps.services.cs_interview import tracing as tracing_module

        monkeypatch.setattr(tracing_module, "DB", database)
        yield database
    database.close()


def test_metadata_sanitization_drops_candidate_content():
    sanitized = _trace_safe_metadata(
        {
            "selected_action": "verify_jd_requirement",
            "target_requirement_id": "req-1",
            "reason": "uncovered",
            "candidate_answer": "I have 5 years of Go and a secret password",
            "reference_answer": "full private reference",
            "hidden_tests": [{"input": 1}],
            "source_text": "JD text",
            "api_key": "sk-secret",
            "evidence_count": 3,
            "score": 4,
        }
    )
    assert sanitized["selected_action"] == "verify_jd_requirement"
    assert sanitized["target_requirement_id"] == "req-1"
    assert sanitized["evidence_count"] == 3
    assert sanitized["score"] == 4
    for leaked in ("candidate_answer", "reference_answer", "hidden_tests", "source_text", "api_key"):
        assert leaked not in sanitized


def test_metadata_sanitization_recurses_into_nested_dicts():
    sanitized = _trace_safe_metadata(
        {
            "budget": {"remaining_question_budget": 2, "answer_text": "secret answer", "max_followups": 3},
        }
    )
    assert sanitized["budget"]["remaining_question_budget"] == 2
    assert sanitized["budget"]["max_followups"] == 3
    assert "answer_text" not in sanitized["budget"]


def test_trace_id_resolution_prefers_operation_then_request_then_session():
    assert resolve_trace_id(operation_id="op-1", request_id="req-1", session_id="s-1") == "op-op-1"
    assert resolve_trace_id(operation_id=None, request_id="req-1", session_id="s-1") == "req-req-1"
    assert resolve_trace_id(operation_id=None, request_id=None, session_id="s-1") == "sess-s-1"
    assert resolve_trace_id(operation_id=None, request_id=None, session_id="s-1", replay=True) == "replay:s-1"


def test_emitter_never_raises_on_flush_failure(trace_db, monkeypatch):
    from api.apps.services.cs_interview import tracing as tracing_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(tracing_module.DB, "atomic", _boom)
    emitter = TraceEmitter()
    emitter.emit(
        TraceEventKind.SESSION_CREATED.value,
        session_id="s-1",
        tenant_id="tenant-1",
        metadata={"selected_action": "verify_jd_requirement"},
    )
    emitter.flush()  # must not raise
    assert emitter.buffered == 0


def test_emitter_writes_sanitized_rows_and_uses_operation_context(trace_db):
    emitter = TraceEmitter()
    token = operation_context.set(
        OperationContext(
            tenant_id="tenant-ctx",
            user_id="user-1",
            session_id="s-ctx",
            operation_id="op-ctx",
            request_id="req-ctx",
            prompt_version="p-1",
            planner_version="pl-1",
        )
    )
    try:
        emitter.emit(
            TraceEventKind.PLANNER_ACTION_SELECTED.value,
            metadata={"selected_action": "finish_interview", "candidate_answer": "secret"},
        )
    finally:
        operation_context.reset(token)
    emitter.flush()

    rows = list(InterviewTraceEvent.select().order_by(InterviewTraceEvent.occurred_at))
    assert len(rows) == 1
    row = rows[0]
    assert row.session_id == "s-ctx"
    assert row.tenant_id == "tenant-ctx"
    assert row.operation_id == "op-ctx"
    assert row.request_id == "req-ctx"
    assert row.trace_id == "op-op-ctx"
    assert row.planner_version == "pl-1"
    assert row.prompt_version == "p-1"
    assert row.event_type == "planner_action_selected"
    assert row.metadata["selected_action"] == "finish_interview"
    assert "candidate_answer" not in row.metadata
    assert "reference_answer" not in str(row.metadata)


def test_emitter_flushes_early_when_buffer_is_full(trace_db):
    emitter = TraceEmitter(max_buffered=3)
    for index in range(6):
        emitter.emit(
            TraceEventKind.ANSWER_RECEIVED.value,
            session_id="s-1",
            tenant_id="t-1",
            metadata={"round_sequence": index},
        )
    assert emitter.buffered == 0
    assert InterviewTraceEvent.select().count() == 6


def test_immediate_emit_persists_and_sanitizes_model_snapshots(trace_db):
    emitter = TraceEmitter()
    emitter.emit(
        TraceEventKind.MODEL_CALL_COMPLETED.value,
        session_id="s-1",
        tenant_id="t-1",
        model_snapshot={"chat": {"llm_name": "safe-model", "api_key": "secret", "headers": {"authorization": "secret"}}},
        input_tokens=12,
        output_tokens=4,
        estimated_cost=0.02,
        duration_ms=80,
        immediate=True,
    )

    assert emitter.buffered == 0
    row = InterviewTraceEvent.get()
    assert row.model_snapshot == {"chat": {"llm_name": "safe-model", "headers": {}}}
    assert row.input_token_count == 12
    assert row.output_token_count == 4
    assert row.estimated_cost == 0.02


def test_trace_retention_cleanup_deletes_old_rows(trace_db, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from api.apps.services.cs_interview import privacy as privacy_module
    from api.apps.services.cs_interview.privacy import RetentionPolicy

    # Older than the retention window, and a fresh row that must survive.
    TRACE_EMITTER.clear()
    old_emitter = TraceEmitter()
    old_emitter.emit(TraceEventKind.SESSION_COMPLETED.value, session_id="s-old", tenant_id="t-1")
    fresh_emitter = TraceEmitter()
    fresh_emitter.emit(TraceEventKind.SESSION_COMPLETED.value, session_id="s-new", tenant_id="t-1")
    old_emitter.flush()
    fresh_emitter.flush()

    now = datetime.now(UTC).replace(tzinfo=None)
    InterviewTraceEvent.update(create_time=int((now - timedelta(days=400)).timestamp() * 1000)).where(
        InterviewTraceEvent.session_id == "s-old"
    ).execute()

    from api.apps.services.cs_interview import tracing as tracing_module

    monkeypatch.setattr(privacy_module, "InterviewTraceEvent", tracing_module.InterviewTraceEvent)
    policy = RetentionPolicy(
        raw_resume_jd_days=365,
        answer_code_days=365,
        session_report_days=730,
        idempotency_days=7,
        event_days=30,
        audit_days=730,
        trace_event_days=180,
    )
    counts = privacy_module.PrivacyService.cleanup(policy=policy, now=now)
    assert counts["trace_events"] == 1
    remaining = {row.session_id for row in InterviewTraceEvent.select()}
    assert remaining == {"s-new"}
