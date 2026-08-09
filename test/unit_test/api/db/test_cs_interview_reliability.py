from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread
from types import SimpleNamespace

import pytest
from peewee import IntegrityError, SqliteDatabase

import api.apps.services.cs_interview.quota as quota_module
import api.db.services.interview_operation_service as operation_persistence
from api.apps.services.cs_interview.domain import DomainError
from api.apps.services.cs_interview.observability import OperationContext, metric_attributes, safe_log_context
from api.apps.services.cs_interview.quota import BudgetService, RedisQuotaManager, estimate_model_cost
from api.apps.services.cs_interview.reliability import classify_failure, retry_delay_seconds
from api.apps.services.cs_interview.runtime import _configured_temperature
from api.apps.services.cs_interview.worker import InterviewWorker
from api.db.db_models import (
    InterviewAuditLog,
    InterviewEvent,
    InterviewModelCall,
    InterviewOperation,
    InterviewOperationCheckpoint,
    InterviewRequest,
    InterviewRound,
    InterviewSession,
)
from api.db.services.interview_operation_service import (
    InterviewOperationService,
    load_external_checkpoint,
    public_event,
    store_external_checkpoint,
)

MODELS = [
    InterviewOperation,
    InterviewRequest,
    InterviewEvent,
    InterviewOperationCheckpoint,
    InterviewModelCall,
    InterviewAuditLog,
    InterviewSession,
    InterviewRound,
]
NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC).replace(tzinfo=None)


@pytest.fixture()
def operation_db(tmp_path, monkeypatch):
    database = SqliteDatabase(tmp_path / "operations.sqlite", timeout=5, pragmas={"journal_mode": "wal"})
    with database.bind_ctx(MODELS, bind_refs=False, bind_backrefs=False):
        database.create_tables(MODELS)
        monkeypatch.setattr(operation_persistence, "DB", database)
        monkeypatch.setattr(quota_module, "DB", database)
        try:
            yield database
        finally:
            database.drop_tables(MODELS)
            database.close()


def _create(*, request_id: str = "request-1", digest: str = "same"):
    return InterviewOperationService.create(
        "tenant-1",
        "user-1",
        "session-1",
        request_id,
        "start_interview",
        digest,
        {"state_version": 0},
        clock=lambda: NOW,
    )


def test_same_request_replays_and_different_payload_conflicts(operation_db):
    operation, replay = _create()
    assert not replay
    same, replay = _create()
    assert replay and same.id == operation.id
    with pytest.raises(DomainError) as error:
        _create(digest="different")
    assert error.value.code == "idempotency_conflict"
    assert InterviewOperation.select().count() == 1
    assert InterviewRequest.select().count() == 1


def test_stale_lease_has_one_winner_across_two_workers(operation_db):
    operation, _ = _create()
    first = InterviewOperationService.claim("worker-a", lease_seconds=5, clock=lambda: NOW)
    assert first.id == operation.id

    barrier = Barrier(3)
    winners: list[str] = []

    def compete(owner: str):
        operation_db.connect(reuse_if_open=True)
        barrier.wait()
        claimed = InterviewOperationService.claim(owner, lease_seconds=5, clock=lambda: NOW + timedelta(seconds=6))
        if claimed:
            winners.append(owner)
        operation_db.close()

    workers = [Thread(target=compete, args=(owner,)) for owner in ("worker-b", "worker-c")]
    for worker in workers:
        worker.start()
    barrier.wait()
    for worker in workers:
        worker.join()

    assert len(winners) == 1
    restored = InterviewOperation.get_by_id(operation.id)
    assert restored.lease_owner == winners[0]
    assert restored.attempt_count == 2


def test_worker_crash_while_preparing_is_reclaimed_and_round_unique_constraint_wins(operation_db):
    InterviewSession.create(
        id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        profile_id="profile-1",
        knowledge_config_id="knowledge-1",
        status="preparing_question",
    )
    operation, _ = _create(request_id="preparing-crash")
    InterviewOperationService.claim("worker-a", lease_seconds=5, clock=lambda: NOW)
    InterviewOperationService.set_stage(operation.id, "worker-a", "prepare_question", clock=lambda: NOW)
    reclaimed = InterviewOperationService.claim("worker-b", lease_seconds=5, clock=lambda: NOW + timedelta(seconds=6))
    assert reclaimed.id == operation.id
    assert reclaimed.attempt_count == 2

    required = {
        "session_id": "session-1",
        "sequence": 1,
        "status": "awaiting_answer",
        "question_id": "question-1",
        "category": "baguwen",
        "topic": "go.runtime",
        "difficulty": "medium",
        "question_text": "Explain Go channel close semantics.",
        "reference_answer": "Private grounded reference answer for the worker crash test.",
        "evaluation_rubric": ["close semantics"],
        "retrieval_query": "go channel close",
        "retrieval_evidence": [{"evidence_id": "evidence-1"}],
    }
    InterviewRound.create(id="round-effective", **required)
    with pytest.raises(IntegrityError) as duplicate:
        InterviewRound.create(id="round-duplicate", **required)
    assert "unique" in str(duplicate.value).lower()
    assert InterviewRound.select().where(InterviewRound.session_id == "session-1").count() == 1


def test_llm_return_checkpoint_is_fenced_and_replayed_after_lease_loss(operation_db):
    operation, _ = _create()
    InterviewOperationService.claim("worker-a", lease_seconds=5, clock=lambda: NOW)
    InterviewOperationService.claim("worker-b", lease_seconds=5, clock=lambda: NOW + timedelta(seconds=6))

    with pytest.raises(DomainError) as error:
        store_external_checkpoint(operation.id, "worker-a", "call-1", "judge", {"output": "old"})
    assert error.value.code == "operation_lease_lost"

    saved, created = store_external_checkpoint(operation.id, "worker-b", "call-1", "judge", {"output": "valid"})
    assert created and saved["output"] == "valid"
    replay, created = store_external_checkpoint(operation.id, "worker-b", "call-1", "judge", {"output": "duplicate"})
    assert not created and replay == {"output": "valid"}
    assert load_external_checkpoint(operation.id, "call-1") == {"output": "valid"}


def test_persisted_events_replay_from_old_sequence_and_strip_secrets(operation_db):
    operation, _ = _create()
    first = InterviewOperationService.append_event(
        operation.id,
        1,
        "feedback",
        {
            "round_id": "round-1",
            "score": 3,
            "feedback": "public",
            "reference_answer": "secret",
            "nested": {"hidden_tests": ["secret"], "feedback": "safe"},
        },
    )
    duplicate = InterviewOperationService.append_event(operation.id, 1, "feedback", {"score": 1})
    second = InterviewOperationService.append_event(
        operation.id,
        2,
        "error",
        {"type": "llm_timeout", "message": "safe", "status": 503, "retryable": True},
    )
    third = InterviewOperationService.append_event(
        operation.id,
        3,
        "next_question",
        {
            "session": {
                "id": "session-1",
                "rounds": [
                    {
                        "question_text": "safe",
                        "candidate_answers": [{"answer": "private answer"}],
                        "resume_probe": {"claim": "private project fact"},
                        "rubric": "internal rubric",
                    }
                ],
            },
            "round": {"id": "round-2", "question_text": "safe"},
        },
    )
    assert duplicate.id == first.id
    assert second.sequence == first.sequence + 1
    replay = InterviewOperationService.list_events("session-1", first.sequence - 1)
    assert [row.sequence for row in replay] == [first.sequence, second.sequence, third.sequence]
    serialized = str([public_event(row) for row in replay])
    assert "reference_answer" not in serialized
    assert "hidden_tests" not in serialized
    assert "secret" not in serialized
    assert "private answer" not in serialized
    assert "private project fact" not in serialized
    assert "internal rubric" not in serialized


def test_worker_event_and_checkpoint_commit_atomically_and_replay_exact_event(operation_db):
    operation, _ = _create()
    claimed = InterviewOperationService.claim("worker-a", lease_seconds=5, clock=lambda: NOW)
    payload = {"session_id": "session-1", "round_id": "round-1"}
    first = InterviewOperationService.append_worker_event(claimed.id, "worker-a", "evaluating", payload, clock=lambda: NOW)
    replay = InterviewOperationService.append_worker_event(claimed.id, "worker-a", "evaluating", payload, clock=lambda: NOW)
    second = InterviewOperationService.append_worker_event(
        claimed.id,
        "worker-a",
        "feedback",
        {"round_id": "round-1", "score": 3, "feedback": "safe"},
        clock=lambda: NOW,
    )

    assert replay.id == first.id
    assert second.operation_sequence == 2
    assert InterviewEvent.select().count() == 2
    refreshed = InterviewOperation.get_by_id(operation.id)
    assert refreshed.checkpoint["event_count"] == 2
    assert refreshed.checkpoint["last_event_type"] == "feedback"


def test_operation_deadline_produces_stable_request_failure(operation_db):
    operation, _ = _create()
    InterviewOperation.update(deadline_at=NOW - timedelta(seconds=1)).where(InterviewOperation.id == operation.id).execute()
    assert InterviewOperationService.claim("worker", clock=lambda: NOW) is None
    failed = InterviewOperation.get_by_id(operation.id)
    request = InterviewRequest.get(InterviewRequest.operation_id == operation.id)
    assert failed.status == "failed"
    assert failed.error_code == "operation_deadline_exceeded"
    assert request.status == "failed"
    assert request.response["error"]["code"] == "operation_deadline_exceeded"


def test_abort_cancels_queued_and_requests_running_cancellation(operation_db):
    pending, _ = _create(request_id="pending")
    running, _ = _create(request_id="running")
    InterviewOperationService.claim("worker", clock=lambda: NOW)
    running = InterviewOperation.get_by_id(running.id)
    if running.status != "running":
        pending, running = running, pending
    changed = InterviewOperationService.cancel_session("session-1", "user_abort", clock=lambda: NOW)
    assert changed == 2
    pending = InterviewOperation.get_by_id(pending.id)
    running = InterviewOperation.get_by_id(running.id)
    assert pending.status == "cancelled"
    assert running.status == "running"
    assert running.cancellation_requested
    assert InterviewOperationService.claim("recovery-worker", clock=lambda: NOW + timedelta(seconds=31)) is None
    assert InterviewOperation.get_by_id(running.id).status == "cancelled"


@pytest.mark.asyncio
async def test_abort_during_judge_cancels_worker_and_prevents_post_call_side_effect(operation_db):
    real_now = datetime.now(UTC).replace(tzinfo=None)
    operation, _ = InterviewOperationService.create(
        "tenant-1",
        "user-1",
        "session-1",
        "judge-abort",
        "evaluate_answer",
        "judge-digest",
        {"answer": "private", "state_version": 1},
        clock=lambda: real_now,
    )
    claimed = InterviewOperationService.claim("worker-a", lease_seconds=5, clock=lambda: real_now)
    started = asyncio.Event()
    side_effects: list[str] = []
    cancelled_runner: list[str] = []

    class BlockingJudgeProcessor:
        quota = SimpleNamespace(acquire_semaphore=lambda *_args, **_kwargs: True)
        application = SimpleNamespace(
            runner=SimpleNamespace(cancel=lambda operation_id: _cancel_runner(operation_id)),
        )

        async def execute(self, running_operation):
            InterviewOperationService.set_stage(running_operation.id, running_operation.lease_owner, "judge")
            started.set()
            await asyncio.Event().wait()
            side_effects.append("next_question")
            return {}

    async def _cancel_runner(operation_id: str):
        cancelled_runner.append(operation_id)

    worker = InterviewWorker(owner="worker-a", processor=BlockingJudgeProcessor())
    worker.lease_seconds = 5
    task = asyncio.create_task(worker.process(claimed))
    await asyncio.wait_for(started.wait(), timeout=1)
    InterviewOperationService.cancel_session("session-1", "user_abort", clock=lambda: real_now)
    await asyncio.wait_for(task, timeout=2)

    restored = InterviewOperation.get_by_id(operation.id)
    assert restored.status == "cancelled"
    assert cancelled_runner == [operation.id]
    assert side_effects == []


def test_retry_classification_and_jitter_are_bounded():
    assert classify_failure(DomainError("llm_rate_limited", "busy", http_status=429)).retryable
    assert classify_failure(DomainError("invalid_judge_output", "bad schema")).retryable is False
    assert classify_failure(TimeoutError()).retryable
    assert retry_delay_seconds(3, random_source=lambda: 0.0) == pytest.approx(3.0)
    assert retry_delay_seconds(3, random_source=lambda: 1.0) == pytest.approx(5.0)


def test_provider_500_timeout_and_schema_failures_have_explicit_retry_policy():
    provider_error = RuntimeError("provider failed")
    provider_error.status_code = 500
    assert classify_failure(provider_error).code == "llm_server_error"
    assert classify_failure(provider_error).retryable
    assert classify_failure(TimeoutError("network timeout")).retryable
    assert classify_failure(DomainError("retrieval_timeout", "slow", http_status=503)).retryable
    assert not classify_failure(DomainError("invalid_judge_output", "invalid JSON")).retryable
    assert not classify_failure(DomainError("insufficient_evidence", "zero evidence")).retryable


def test_token_cost_call_budgets_and_unknown_model_price_fail_closed(operation_db, monkeypatch):
    InterviewSession.create(
        id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        profile_id="profile-1",
        knowledge_config_id="knowledge-1",
        total_prompt_tokens=60,
        total_completion_tokens=30,
        total_estimated_cost=0.5,
    )
    monkeypatch.setenv("CS_INTERVIEW_MAX_SESSION_TOKENS", "100")
    monkeypatch.setenv("CS_INTERVIEW_MAX_SESSION_COST", "1")
    monkeypatch.setenv("CS_INTERVIEW_TENANT_BUDGET_CENTS_TENANT_1", "40")
    with pytest.raises(DomainError, match="token budget") as token_error:
        BudgetService.check_before_llm("session-1", 11)
    assert token_error.value.code == "token_budget_exhausted"

    InterviewSession.update(total_prompt_tokens=0, total_completion_tokens=0, total_estimated_cost=0.41).where(
        InterviewSession.id == "session-1"
    ).execute()
    with pytest.raises(DomainError, match="cost budget") as cost_error:
        BudgetService.check_before_llm("session-1", 1)
    assert cost_error.value.code == "cost_budget_exhausted"

    InterviewSession.update(total_estimated_cost=0, cost_unknown=True).where(InterviewSession.id == "session-1").execute()
    monkeypatch.setenv("CS_INTERVIEW_FAIL_ON_UNKNOWN_COST", "true")
    with pytest.raises(DomainError) as unknown_error:
        BudgetService.check_before_llm("session-1", 1)
    assert unknown_error.value.code == "cost_unknown"
    assert estimate_model_cost("unpriced-model", 1000, 1000) is None

    operation, _ = _create(request_id="call-budget")
    assert BudgetService.reserve_operation_call(operation.id, "llm_calls", 2, "llm_call_budget_exhausted") == 1
    assert BudgetService.reserve_operation_call(operation.id, "llm_calls", 2, "llm_call_budget_exhausted") == 2
    with pytest.raises(DomainError) as call_error:
        BudgetService.reserve_operation_call(operation.id, "llm_calls", 2, "llm_call_budget_exhausted")
    assert call_error.value.code == "llm_call_budget_exhausted"


class _FakeRedisClient:
    def __init__(self):
        self.values: dict[str, float] = {}


class _FakeRedis:
    def __init__(self):
        self.REDIS = _FakeRedisClient()

        def bucket(*, keys, args, client):
            key = keys[0]
            capacity, _rate, _now, cost = map(float, args)
            used = client.values.get(key, 0.0)
            if used + cost > capacity:
                return [0, capacity - used]
            client.values[key] = used + cost
            return [1, capacity - used - cost]

        self.lua_token_bucket = bucket


def test_two_api_replicas_share_the_same_redis_rate_limit():
    backend = _FakeRedis()
    replica_a = RedisQuotaManager(backend)
    replica_b = RedisQuotaManager(backend)
    replica_a.token_bucket("user-write:user-1", 2)
    replica_b.token_bucket("user-write:user-1", 2)
    with pytest.raises(DomainError) as error:
        replica_a.token_bucket("user-write:user-1", 2)
    assert error.value.code == "rate_limited"


def test_redis_outage_fails_quota_closed_instead_of_using_process_memory():
    manager = RedisQuotaManager(SimpleNamespace(REDIS=None))
    with pytest.raises(DomainError) as error:
        manager.check_write_rate("user-1")
    assert error.value.code == "quota_backend_unavailable"


def test_metric_attributes_reject_high_cardinality_ids():
    attributes = metric_attributes(
        operation_type="evaluate_answer",
        status="completed",
        session_id="session-secret",
        round_id="round-secret",
        tenant_id="tenant-secret",
    )
    assert attributes == {"operation_type": "evaluate_answer", "status": "completed"}


def test_safe_log_context_drops_sensitive_dynamic_fields_and_hashes_user_id():
    context = OperationContext(
        tenant_id="tenant-1",
        user_id="user-secret",
        session_id="session-1",
        operation_id="operation-1",
        request_id="request-1",
    )
    values = safe_log_context(
        context,
        status="failed",
        prompt="prompt-secret",
        answer="answer-secret",
        source_code="source-secret",
        evidence="evidence-secret",
    )
    serialized = str(values)
    assert values["status"] == "failed"
    assert values["user_id_hash"] != "user-secret"
    assert "user-secret" not in serialized
    assert "prompt-secret" not in serialized
    assert "answer-secret" not in serialized
    assert "source-secret" not in serialized
    assert "evidence-secret" not in serialized


def test_experiment_temperature_overrides_the_stage_default():
    context = OperationContext(
        tenant_id="tenant-1",
        user_id="user-1",
        session_id="session-1",
        operation_id="operation-1",
        request_id="request-1",
        runtime_config={"temperature": 0.4, "temperatures": {"judge": 0.0}},
    )
    assert _configured_temperature(context, "generate_question", 0.1) == 0.4
    assert _configured_temperature(context, "judge", 0.8) == 0.0
