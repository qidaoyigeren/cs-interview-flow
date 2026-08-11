"""Ops DTO leak, redaction, and tenant-isolation tests (no external services)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from peewee import SqliteDatabase

from api.apps.services.cs_interview.ops_service import (
    _redact,
    blocked_resource_ids,
    list_feedback,
    quality_overview,
    record_review,
    session_audit,
    submit_feedback,
)
from api.db.db_models import (
    CodeSubmission,
    InterviewAuditLog,
    InterviewFeedback,
    InterviewJob,
    InterviewKnowledgeConfig,
    InterviewModelCall,
    InterviewOperation,
    InterviewProfile,
    InterviewReport,
    InterviewReviewAction,
    InterviewRound,
    InterviewSession,
    InterviewTraceEvent,
)

MODELS = [
    InterviewJob,
    InterviewProfile,
    InterviewKnowledgeConfig,
    InterviewSession,
    InterviewRound,
    InterviewReport,
    CodeSubmission,
    InterviewTraceEvent,
    InterviewFeedback,
    InterviewAuditLog,
    InterviewModelCall,
    InterviewReviewAction,
    InterviewOperation,
]
NOW = datetime.now(UTC).replace(tzinfo=None)


def _timestamps():
    millis = int(NOW.timestamp() * 1000)
    return {"create_time": millis, "update_time": millis}


@pytest.fixture
def ops_db(monkeypatch):
    database = SqliteDatabase(":memory:")
    with database.bind_ctx(MODELS, bind_refs=False, bind_backrefs=False):
        database.create_tables(MODELS)
        from api.apps.services.cs_interview import tracing as tracing_module
        from api.db.services import interview_operation_service as operation_persistence

        monkeypatch.setattr(operation_persistence, "DB", database)
        monkeypatch.setattr(tracing_module, "DB", database)
        yield database
    database.close()


def _session(tenant_id="tenant-1", session_id="session-1", status="completed"):
    return InterviewSession.create(
        id=session_id,
        tenant_id=tenant_id,
        user_id="user-1",
        profile_id="profile-1",
        knowledge_config_id="config-1",
        status=status,
        current_difficulty="medium",
        max_questions=2,
        max_followups=2,
        completed_question_count=1,
        current_round_sequence=1,
        state_version=1,
        model_config_snapshot={},
        knowledge_base_versions={},
        performance_snapshot={},
        planner_version="cs-interview-planner-v1",
        prompt_version="cs-interview-v1",
        **_timestamps(),
    )


def test_redact_exposes_only_length_and_hash():
    summary = _redact("private candidate answer with sensitive details")
    assert "private" not in summary
    assert summary.startswith("len=")
    assert "hash=" in summary
    assert _redact("") == ""
    # Same input -> same hash (deterministic).
    assert _redact("abc") == _redact("abc")


def test_session_audit_never_exposes_answer_content(ops_db):
    session = _session()
    InterviewRound.create(
        id="round-1",
        session_id=session.id,
        sequence=1,
        status="completed",
        topic="go.runtime",
        category="baguwen",
        question_type="theory",
        difficulty="medium",
        question_id="go-channel-001",
        question_text="Explain channel close.",
        reference_answer="private reference answer",
        evaluation_rubric=["rubric"],
        retrieval_query="q",
        retrieval_evidence=[],
        candidate_answers=[{"kind": "initial", "answer": "secret answer content", "evaluation": {"score": 3}}],
        answer_state={},
        planner_actions=[{"selected_action": "verify_resume_claim", "reason": "Verify the JD requirement."}],
        score=3,
        verdict="partial",
        **_timestamps(),
    )
    InterviewTraceEvent.create(
        id="trace-1",
        trace_id="t-1",
        event_id="e-1",
        session_id=session.id,
        tenant_id="tenant-1",
        event_type="session_completed",
        occurred_at=NOW,
        status="succeeded",
        **_timestamps(),
    )
    audit = session_audit(session.id, "tenant-1")
    assert audit["rounds"][0]["answer_summary"].startswith("len=")
    assert "secret answer content" not in json.dumps(audit)
    assert "private reference answer" not in json.dumps(audit)
    assert audit["timeline"][0]["event_type"] == "session_completed"
    # The stored planner reason is redacted in the audit trail.
    assert "Verify the JD requirement" not in json.dumps(audit)


def test_feedback_tenant_isolation(ops_db):
    _session(tenant_id="tenant-1", session_id="session-1")
    _session(tenant_id="tenant-2", session_id="session-2")
    submit_feedback(
        tenant_id="tenant-1",
        user_id="user-1",
        session_id="session-1",
        kind="unfair_scoring",
        message="score seems wrong",
        prompt_version="cs-interview-v1",
        planner_version="cs-interview-planner-v1",
    )
    rows_1 = list_feedback(tenant_id="tenant-1")
    assert len(rows_1) == 1
    assert rows_1[0]["kind"] == "unfair_scoring"
    assert rows_1[0]["prompt_version"] == "cs-interview-v1"
    assert rows_1[0]["planner_version"] == "cs-interview-planner-v1"
    assert list_feedback(tenant_id="tenant-2") == []


def test_feedback_derives_versions_and_validates_round_evidence(ops_db):
    session = _session()
    round_ = InterviewRound.create(
        id="round-feedback",
        session_id=session.id,
        sequence=1,
        status="completed",
        topic="go.runtime",
        category="baguwen",
        question_type="theory",
        difficulty="medium",
        question_id="question-real",
        question_text="Explain channel close.",
        reference_answer="reference",
        evaluation_rubric=["point"],
        retrieval_query="query",
        retrieval_evidence=[{"evidence_id": "evidence-real"}],
        evidence_versions=[{"evidence_id": "evidence-real"}],
        model_version="model-real",
        prompt_version="prompt-real",
        **_timestamps(),
    )
    result = submit_feedback(
        tenant_id="tenant-1",
        user_id="user-1",
        session_id=session.id,
        round_id=round_.id,
        evidence_id="evidence-real",
        model="forged-model",
        prompt_version="forged-prompt",
        planner_version="forged-planner",
        kind="technical_error",
        message="evidence is stale",
    )
    row = InterviewFeedback.get_by_id(result["id"])
    assert row.question_id == "question-real"
    assert row.evidence_id == "evidence-real"
    assert row.model == "model-real"
    assert row.prompt_version == "prompt-real"
    assert row.planner_version == session.planner_version
    assert InterviewTraceEvent.select().where(InterviewTraceEvent.event_type == "user_feedback_received").count() == 1

    with pytest.raises(Exception, match="does not belong"):
        submit_feedback(
            tenant_id="tenant-1",
            user_id="user-1",
            session_id=session.id,
            round_id=round_.id,
            evidence_id="evidence-forged",
            kind="technical_error",
            message="bad link",
        )


def test_governance_actions_are_tenant_scoped_and_latest_action_controls_blocking(ops_db):
    session = _session()
    InterviewRound.create(
        id="round-governance",
        session_id=session.id,
        sequence=1,
        status="completed",
        topic="go.runtime",
        category="baguwen",
        question_type="theory",
        difficulty="medium",
        question_id="question-blocked",
        question_text="Explain channel close.",
        reference_answer="reference",
        evaluation_rubric=["point"],
        retrieval_query="query",
        retrieval_evidence=[{"evidence_id": "evidence-blocked"}],
        **_timestamps(),
    )
    result = record_review(
        reviewer_id_hash="admin-1",
        resource_type="question",
        resource_id="question-blocked",
        action="take_down",
        comment="grounding issue",
        tenant_id="tenant-1",
    )
    assert result["blocked"] is True
    assert result["reevaluation_required"] is True
    assert blocked_resource_ids("tenant-1", "question") == {"question-blocked"}
    assert blocked_resource_ids("tenant-2", "question") == set()

    record_review(
        reviewer_id_hash="admin-2",
        resource_type="question",
        resource_id="question-blocked",
        action="review",
        comment="fixed and approved",
        tenant_id="tenant-1",
    )
    assert blocked_resource_ids("tenant-1", "question") == set()


def test_quality_overview_aggregates_trace_events(ops_db):
    for index, event_type in enumerate(("session_completed", "session_failed", "answer_received", "evidence_rejected")):
        InterviewTraceEvent.create(
            id=f"trace-{index}",
            trace_id=f"t-{index}",
            event_id=f"e-{index}",
            session_id=f"session-{index}",
            tenant_id="tenant-1",
            event_type=event_type,
            occurred_at=NOW,
            status="failed" if event_type == "session_failed" else "succeeded",
            duration_ms=150 if index % 2 == 0 else 450,
            input_token_count=10,
            output_token_count=5,
            estimated_cost=0.01,
            planner_version="pl-v1",
            prompt_version="p-v1",
            **_timestamps(),
        )
        InterviewModelCall.create(
            id=f"model-call-{index}",
            tenant_id="tenant-1",
            session_id=f"session-{index}",
            operation_id=f"operation-{index}",
            stage="judge",
            model="model-v1",
            prompt_tokens=10,
            completion_tokens=5,
            estimated_cost=0.01,
            cost_unknown=False,
            status="completed",
            **_timestamps(),
        )
    overview = quality_overview(tenant_id="tenant-1", since_hours=24)
    assert overview["session_count"] == 2
    assert overview["session_success_rate"] == 0.5
    assert overview["session_failure_count"] == 1
    assert overview["answer_request_count"] == 1
    assert overview["evidence_rejected_count"] == 1
    assert overview["tokens"] == {"input": 40, "output": 20}
    assert overview["version_distribution"]["planner_version"]["pl-v1"] == 4
    assert overview["latency_p50_p95"]["answer_received"]["p50"] == 150
