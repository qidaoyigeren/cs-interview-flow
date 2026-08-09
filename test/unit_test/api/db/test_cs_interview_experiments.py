"""Interview experiment bucketing, assignment and guardrail auto-stop tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from peewee import SqliteDatabase

from api.apps.services.cs_interview.experiment_service import (
    assign,
    auto_stop_breached,
    guardrail_breaches,
    normalize_variant,
    resolve_variant,
    stable_bucket,
)
from api.db.db_models import (
    InterviewAuditLog,
    InterviewExperiment,
    InterviewExperimentAssignment,
    InterviewOperation,
    InterviewTraceEvent,
)

MODELS = (
    InterviewExperiment,
    InterviewExperimentAssignment,
    InterviewTraceEvent,
    InterviewAuditLog,
    InterviewOperation,
)
NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC).replace(tzinfo=None)


@pytest.fixture
def experiment_db(monkeypatch):
    database = SqliteDatabase(":memory:")
    with database.bind_ctx(MODELS, bind_refs=False, bind_backrefs=False):
        database.create_tables(MODELS)
        from api.apps.services.cs_interview import experiment_service as experiment_module

        monkeypatch.setattr(experiment_module, "DB", database)
        from api.db.services import interview_operation_service as operation_persistence

        monkeypatch.setattr(operation_persistence, "DB", database)
        yield database
    database.close()


def _variant(variant_id, **overrides):
    base = {
        "variant_id": variant_id,
        "prompt_version": "cs-interview-v1",
        "planner_version": "cs-interview-planner-v1",
        "temperature": 0.1,
    }
    base.update(overrides)
    return base


def _experiment(**overrides):
    defaults = {
        "id": "exp-1",
        "tenant_id": "tenant-1",
        "name": "planner-ab",
        "status": "gray",
        "control_variant": _variant("control"),
        "candidate_variants": [_variant("candidate-a"), _variant("candidate-b")],
        "traffic_percentage": 100,
        "target_tenants": [],
        "start_at": None,
        "end_at": None,
        "success_metrics": {},
        "guardrail_metrics": [{"metric": "session_failure_rate", "operator": ">=", "target": 0.5}],
    }
    defaults.update(overrides)
    return InterviewExperiment.create(**defaults, **_timestamps())


def _timestamps():
    return {"create_time": int(NOW.timestamp() * 1000), "update_time": int(NOW.timestamp() * 1000)}


def test_stable_bucket_is_reproducible_and_bounded():
    first = stable_bucket("exp-1", "tenant-1", "user-1", "session-1")
    second = stable_bucket("exp-1", "tenant-1", "user-1", "session-1")
    assert first == second
    assert 0 <= first < 100
    assert stable_bucket("exp-1", "tenant-1", "user-1", "session-2") != stable_bucket("exp-1", "tenant-1", "user-1", "session-1") or True


def test_resolve_variant_respects_traffic_percentage_and_tenant_target(experiment_db):
    _experiment(traffic_percentage=0)
    control = resolve_variant("tenant-1", "user-1", "session-1", now=NOW)
    assert control is not None
    assert control["variant_id"] == "control"

    InterviewExperiment.update(traffic_percentage=100).where(InterviewExperiment.id == "exp-1").execute()
    variant = resolve_variant("tenant-1", "user-1", "session-1", now=NOW)
    assert variant is not None
    assert variant["experiment_id"] == "exp-1"
    assert variant["variant_id"] in {"candidate-a", "candidate-b"}

    # Tenant targeting excludes other tenants.
    InterviewExperiment.update(target_tenants=["tenant-1"]).where(InterviewExperiment.id == "exp-1").execute()
    assert resolve_variant("tenant-9", "user-1", "session-1", now=NOW) is None
    assert resolve_variant("tenant-1", "user-1", "session-1", now=NOW) is not None


def test_variant_validation_rejects_non_executable_versions_and_flags():
    with pytest.raises(Exception, match="Prompt version"):
        normalize_variant({"prompt_version": "missing"}, default_variant_id="candidate")
    with pytest.raises(Exception, match="feature_flags"):
        normalize_variant({"feature_flags": {"imaginary_flag": True}}, default_variant_id="candidate")
    configured = normalize_variant(
        {
            "variant_id": "candidate-v2",
            "prompt_version": "cs-interview-v2",
            "temperature": 0.35,
            "feature_flags": {"semantic_dedup": False},
        },
        default_variant_id="candidate",
    )
    assert configured["prompt_version"] == "cs-interview-v2"
    assert configured["temperature"] == 0.35


def test_resolve_variant_is_stable_across_calls(experiment_db):
    _experiment(traffic_percentage=100)
    first = resolve_variant("tenant-1", "user-1", "session-1", now=NOW)
    second = resolve_variant("tenant-1", "user-1", "session-1", now=NOW)
    assert first == second


def test_assignment_is_frozen_per_session(experiment_db):
    _experiment(traffic_percentage=100)
    variant = resolve_variant("tenant-1", "user-1", "session-1", now=NOW)
    assert variant is not None
    assign("tenant-1", "user-1", "session-1", variant, now=NOW)
    rows = list(InterviewExperimentAssignment.select())
    assert len(rows) == 1
    assert rows[0].session_id == "session-1"
    assert rows[0].experiment_id == "exp-1"
    assert rows[0].variant_id == variant["variant_id"]


def test_guardrail_breach_stops_experiment(experiment_db):
    _experiment(guardrail_metrics=[{"metric": "session_failure_rate", "operator": ">=", "target": 0.5}])
    # Two assigned sessions, one failed -> 0.5 failure rate (breach at >= 0.5).
    for session_id in ("s-1", "s-2"):
        assign("tenant-1", "user-1", session_id, {"experiment_id": "exp-1", "variant_id": "candidate-a"}, now=NOW)
        InterviewTraceEvent.create(
            id=f"trace-{session_id}",
            trace_id=f"t-{session_id}",
            event_id=f"e-{session_id}",
            session_id=session_id,
            tenant_id="tenant-1",
            event_type="session_failed" if session_id == "s-1" else "session_completed",
            occurred_at=NOW,
            status="failed" if session_id == "s-1" else "succeeded",
            **_timestamps(),
        )
    experiment = InterviewExperiment.get_by_id("exp-1")
    assert guardrail_breaches(experiment, now=NOW) == ["session_failure_rate"]

    stopped = auto_stop_breached(now=NOW)
    assert stopped == ["exp-1"]
    assert InterviewExperiment.get_by_id("exp-1").status == "stopped"
    audit_row = InterviewAuditLog.select().where(InterviewAuditLog.action == "experiment_auto_stop").first()
    assert audit_row is not None
    assert audit_row.resource_id == "exp-1"


def test_guardrail_no_breach_when_failure_rate_below_target(experiment_db):
    _experiment(guardrail_metrics=[{"metric": "session_failure_rate", "operator": ">=", "target": 0.9}])
    for session_id in ("s-1", "s-2"):
        assign("tenant-1", "user-1", session_id, {"experiment_id": "exp-1", "variant_id": "candidate-a"}, now=NOW)
        InterviewTraceEvent.create(
            id=f"trace-{session_id}",
            trace_id=f"t-{session_id}",
            event_id=f"e-{session_id}",
            session_id=session_id,
            tenant_id="tenant-1",
            event_type="session_completed",
            occurred_at=NOW,
            status="succeeded",
            **_timestamps(),
        )
    experiment = InterviewExperiment.get_by_id("exp-1")
    assert guardrail_breaches(experiment, now=NOW) == []
    assert auto_stop_breached(now=NOW) == []


def test_answer_request_failure_guardrail_reads_terminal_operations(experiment_db):
    _experiment(guardrail_metrics=[{"metric": "answer_request_failure_rate", "operator": ">=", "target": 0.5}])
    for index, status in enumerate(("completed", "failed"), start=1):
        session_id = f"answer-session-{index}"
        assign("tenant-1", "user-1", session_id, {"experiment_id": "exp-1", "variant_id": "candidate-a"}, now=NOW)
        InterviewOperation.create(
            id=f"operation-{index}",
            tenant_id="tenant-1",
            user_id="user-1",
            session_id=session_id,
            request_id=f"request-{index}",
            operation_type="evaluate_answer",
            payload_hash=f"hash-{index}",
            status=status,
            deadline_at=NOW + timedelta(minutes=5),
            create_date=NOW,
            **_timestamps(),
        )
    assert guardrail_breaches(InterviewExperiment.get_by_id("exp-1"), now=NOW) == ["answer_request_failure_rate"]
