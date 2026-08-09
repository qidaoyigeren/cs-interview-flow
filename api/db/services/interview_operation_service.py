"""Durable operation, event, idempotency, and retention persistence."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from peewee import IntegrityError, fn

from api.apps.services.cs_interview.domain import DomainError
from api.apps.services.cs_interview.reliability import TERMINAL_OPERATION_STATUSES, OperationStatus, OperationType
from api.db.db_models import (
    DB,
    InterviewAuditLog,
    InterviewEvent,
    InterviewModelCall,
    InterviewOperation,
    InterviewOperationCheckpoint,
    InterviewRequest,
)
from api.db.services.interview_service import _public_json, _timestamps, _touch
from common.misc_utils import get_uuid

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _positive_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


_REQUEST_OPERATION = {
    OperationType.START_INTERVIEW.value: "start",
    OperationType.EVALUATE_ANSWER.value: "answer",
    OperationType.EXECUTE_CODE.value: "code",
}


_EVENT_FIELDS: dict[str, frozenset[str]] = {
    "answer_received": frozenset({"session_id", "round_id", "state_version"}),
    "evaluating": frozenset({"session_id", "round_id"}),
    "feedback": frozenset({"round_id", "score", "verdict", "weak_point", "feedback", "evaluation_summary", "final", "next_difficulty", "next_action", "next_action_reason"}),
    "followup_question": frozenset({"session_id", "round_id", "question", "selected_action", "reason", "followup_count", "max_followups", "state_version"}),
    "next_question": frozenset({"session", "round"}),
    "interview_completed": frozenset({"session", "report"}),
    "code_completed": frozenset({"submission"}),
    "error": frozenset({"type", "message", "status", "retryable"}),
    "session_aborted": frozenset({"session_id", "reason"}),
}


_FORBIDDEN_KEYS = {
    "answer",
    "candidate_answers",
    "resume_probe",
    "reference_answer",
    "reference_solution",
    "rubric",
    "evaluation_rubric",
    "evidence",
    "evidence_text",
    "retrieval_evidence",
    "hidden_tests",
    "prompt",
    "prompt_snapshot",
    "source_code",
    "checkpoint",
    "supporting_state",
}


def _clean_public(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _clean_public(item) for key, item in value.items() if key not in _FORBIDDEN_KEYS}
    if isinstance(value, list):
        return [_clean_public(item) for item in value]
    return _public_json(value)


def public_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = _EVENT_FIELDS.get(event_type)
    if allowed is None:
        raise DomainError("invalid_event_type", "The worker produced an unsupported public event.")
    return _clean_public({key: payload[key] for key in allowed if key in payload})


def public_operation(operation: InterviewOperation) -> dict[str, Any]:
    return _public_json(
        {
            "id": operation.id,
            "session_id": operation.session_id,
            "round_id": operation.round_id,
            "request_id": operation.request_id,
            "operation_type": operation.operation_type,
            "status": operation.status,
            "current_stage": operation.current_stage,
            "attempt_count": operation.attempt_count,
            "max_attempts": operation.max_attempts,
            "lease_expires_at": operation.lease_expires_at,
            "next_retry_at": operation.next_retry_at,
            "deadline_at": operation.deadline_at,
            "cancellation_requested": operation.cancellation_requested,
            "error_code": operation.error_code,
            "error_class": operation.error_class,
            "result_summary": _clean_public(operation.result_summary or {}),
            "started_at": operation.started_at,
            "completed_at": operation.completed_at,
            "created_at": operation.create_date,
            "updated_at": operation.update_date,
        }
    )


def public_event(event: InterviewEvent) -> dict[str, Any]:
    return _public_json(
        {
            "id": event.sequence,
            "sequence": event.sequence,
            "operation_id": event.operation_id,
            "event": event.event_type,
            "data": event.public_payload,
            "created_at": event.create_date,
        }
    )


class InterviewOperationService:
    @staticmethod
    def create(
        tenant_id: str,
        user_id: str,
        session_id: str,
        request_id: str,
        operation_type: str,
        payload_hash: str,
        payload: dict[str, Any],
        *,
        round_id: str | None = None,
        clock: Clock = _utcnow,
    ) -> tuple[InterviewOperation, bool]:
        if not request_id or len(request_id) > 128:
            raise DomainError("invalid_request_id", "request_id is required and must be at most 128 characters.")
        if operation_type not in {item.value for item in OperationType}:
            raise DomainError("invalid_operation_type", "Unsupported interview operation type.")
        existing = InterviewOperation.get_or_none((InterviewOperation.session_id == session_id) & (InterviewOperation.request_id == request_id))
        if existing:
            if existing.tenant_id != tenant_id or existing.user_id != user_id:
                raise DomainError("operation_not_found", "Interview operation not found.", http_status=404)
            if existing.payload_hash != payload_hash or existing.operation_type != operation_type:
                raise DomainError("idempotency_conflict", "request_id was already used with another payload.", http_status=409)
            return existing, True
        now = clock()
        deadline = now + timedelta(seconds=_positive_env("CS_INTERVIEW_MAX_OPERATION_SECONDS", 300))
        request_expiry = now + timedelta(days=_positive_env("CS_INTERVIEW_IDEMPOTENCY_RETENTION_DAYS", 7))
        operation_id = get_uuid()
        try:
            with DB.atomic():
                operation = InterviewOperation.create(
                    id=operation_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                    round_id=round_id,
                    request_id=request_id,
                    operation_type=operation_type,
                    payload_hash=payload_hash,
                    payload=payload,
                    status=OperationStatus.PENDING.value,
                    current_stage="queued",
                    checkpoint={},
                    max_attempts=_positive_env("CS_INTERVIEW_OPERATION_MAX_ATTEMPTS", 4),
                    deadline_at=deadline,
                    **_timestamps(),
                )
                InterviewRequest.create(
                    id=get_uuid(),
                    session_id=session_id,
                    request_id=request_id,
                    operation=_REQUEST_OPERATION.get(operation_type, operation_type),
                    payload_hash=payload_hash,
                    status="queued",
                    response={},
                    operation_id=operation_id,
                    expires_at=request_expiry,
                    **_timestamps(),
                )
            return operation, False
        except IntegrityError:
            existing = InterviewOperation.get_or_none((InterviewOperation.session_id == session_id) & (InterviewOperation.request_id == request_id))
            if existing and existing.payload_hash == payload_hash and existing.operation_type == operation_type:
                return existing, True
            raise DomainError("idempotency_conflict", "request_id was already used with another payload.", http_status=409)

    @staticmethod
    def get(operation_id: str, tenant_id: str, user_id: str) -> InterviewOperation:
        operation = InterviewOperation.get_or_none(
            (InterviewOperation.id == operation_id)
            & (InterviewOperation.tenant_id == tenant_id)
            & (InterviewOperation.user_id == user_id)
        )
        if operation is None:
            raise DomainError("operation_not_found", "Interview operation not found.", http_status=404)
        return operation

    @staticmethod
    def claim(owner: str, *, lease_seconds: int | None = None, clock: Clock = _utcnow) -> InterviewOperation | None:
        now = clock()
        lease_seconds = lease_seconds or _positive_env("CS_INTERVIEW_OPERATION_LEASE_SECONDS", 30)
        expired_cancellations = (
            (InterviewOperation.status == OperationStatus.RUNNING.value)
            & InterviewOperation.cancellation_requested
            & (InterviewOperation.lease_expires_at.is_null(False))
            & (InterviewOperation.lease_expires_at <= now)
        )
        cancelled_ids = [row.id for row in InterviewOperation.select(InterviewOperation.id).where(expired_cancellations)]
        if cancelled_ids:
            InterviewOperation.update(
                status=OperationStatus.CANCELLED.value,
                current_stage="cancelled",
                payload={},
                lease_owner=None,
                lease_expires_at=None,
                stage_deadline_at=None,
                completed_at=now,
                **_touch(),
            ).where(expired_cancellations & InterviewOperation.id.in_(cancelled_ids)).execute()
            InterviewRequest.update(
                status="cancelled",
                response={"error": {"code": "operation_cancelled"}},
                **_touch(),
            ).where(InterviewRequest.operation_id.in_(cancelled_ids)).execute()
        eligible = (
            (InterviewOperation.status == OperationStatus.PENDING.value)
            | (
                (InterviewOperation.status == OperationStatus.RETRY_WAIT.value)
                & ((InterviewOperation.next_retry_at.is_null(True)) | (InterviewOperation.next_retry_at <= now))
            )
            | (
                (InterviewOperation.status == OperationStatus.RUNNING.value)
                & (InterviewOperation.lease_expires_at.is_null(False))
                & (InterviewOperation.lease_expires_at <= now)
            )
        ) & (InterviewOperation.attempt_count < InterviewOperation.max_attempts)
        claimable = eligible & ~InterviewOperation.cancellation_requested & (InterviewOperation.deadline_at > now)
        candidates = list(
            InterviewOperation.select()
            .where(claimable)
            .order_by(InterviewOperation.create_time.asc())
            .limit(8)
        )
        for candidate in candidates:
            condition = (InterviewOperation.id == candidate.id) & claimable
            changed = (
                InterviewOperation.update(
                    status=OperationStatus.RUNNING.value,
                    lease_owner=owner,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                    heartbeat_at=now,
                    next_retry_at=None,
                    attempt_count=InterviewOperation.attempt_count + 1,
                    started_at=fn.COALESCE(InterviewOperation.started_at, now),
                    **_touch(),
                )
                .where(condition)
                .execute()
            )
            if changed == 1:
                return InterviewOperation.get_by_id(candidate.id)
        active_status = InterviewOperation.status.in_(
            (OperationStatus.PENDING.value, OperationStatus.RETRY_WAIT.value, OperationStatus.RUNNING.value)
        )
        terminal_groups = (
            (
                active_status & (InterviewOperation.deadline_at <= now),
                "operation_deadline_exceeded",
                "DeadlineExceeded",
                504,
            ),
            (
                active_status
                & (InterviewOperation.deadline_at > now)
                & (InterviewOperation.attempt_count >= InterviewOperation.max_attempts),
                "operation_attempts_exhausted",
                "AttemptsExhausted",
                409,
            ),
        )
        for condition, code, error_class, http_status in terminal_groups:
            terminal_ids = [row.id for row in InterviewOperation.select(InterviewOperation.id).where(condition)]
            if not terminal_ids:
                continue
            InterviewOperation.update(
                status=OperationStatus.FAILED.value,
                current_stage="failed",
                error_code=code,
                error_class=error_class,
                payload={},
                completed_at=now,
                lease_owner=None,
                lease_expires_at=None,
                **_touch(),
            ).where(condition & InterviewOperation.id.in_(terminal_ids)).execute()
            failed_ids = [
                row.id
                for row in InterviewOperation.select(InterviewOperation.id).where(
                    InterviewOperation.id.in_(terminal_ids)
                    & (InterviewOperation.status == OperationStatus.FAILED.value)
                    & (InterviewOperation.error_code == code)
                )
            ]
            if not failed_ids:
                continue
            InterviewRequest.update(
                status="failed",
                response={"error": {"code": code, "http_status": http_status}},
                **_touch(),
            ).where(InterviewRequest.operation_id.in_(failed_ids)).execute()
        return None

    @staticmethod
    def renew(operation_id: str, owner: str, *, lease_seconds: int | None = None, clock: Clock = _utcnow) -> bool:
        now = clock()
        lease_seconds = lease_seconds or _positive_env("CS_INTERVIEW_OPERATION_LEASE_SECONDS", 30)
        return (
            InterviewOperation.update(
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                **_touch(),
            )
            .where(
                (InterviewOperation.id == operation_id)
                & (InterviewOperation.status == OperationStatus.RUNNING.value)
                & (InterviewOperation.lease_owner == owner)
            )
            .execute()
            == 1
        )

    @staticmethod
    def set_stage(operation_id: str, owner: str, stage: str, checkpoint: dict[str, Any] | None = None, *, clock: Clock = _utcnow) -> InterviewOperation:
        deadline = clock() + timedelta(seconds=_positive_env("CS_INTERVIEW_STAGE_DEADLINE_SECONDS", 120))
        values: dict[str, Any] = {"current_stage": stage, "stage_deadline_at": deadline, **_touch()}
        if checkpoint is not None:
            current = InterviewOperation.get_or_none(
                (InterviewOperation.id == operation_id)
                & (InterviewOperation.status == OperationStatus.RUNNING.value)
                & (InterviewOperation.lease_owner == owner)
            )
            if current is None:
                raise DomainError("operation_lease_lost", "The operation lease was lost.", http_status=409)
            values["checkpoint"] = {**dict(current.checkpoint or {}), **checkpoint}
        changed = InterviewOperation.update(**values).where(
            (InterviewOperation.id == operation_id)
            & (InterviewOperation.status == OperationStatus.RUNNING.value)
            & (InterviewOperation.lease_owner == owner)
        ).execute()
        if changed != 1:
            raise DomainError("operation_lease_lost", "The operation lease was lost.", http_status=409)
        return InterviewOperation.get_by_id(operation_id)

    @staticmethod
    def complete(operation_id: str, owner: str, result_summary: dict[str, Any], *, clock: Clock = _utcnow) -> bool:
        now = clock()
        changed = InterviewOperation.update(
            status=OperationStatus.COMPLETED.value,
            current_stage="completed",
            result_summary=_clean_public(result_summary),
            payload={},
            lease_owner=None,
            lease_expires_at=None,
            stage_deadline_at=None,
            completed_at=now,
            **_touch(),
        ).where(
            (InterviewOperation.id == operation_id)
            & (InterviewOperation.status == OperationStatus.RUNNING.value)
            & (InterviewOperation.lease_owner == owner)
        ).execute()
        if changed:
            InterviewRequest.update(status="completed", response=_clean_public(result_summary), **_touch()).where(
                InterviewRequest.operation_id == operation_id
            ).execute()
        return changed == 1

    @staticmethod
    def retry(operation_id: str, owner: str, code: str, error_class: str, delay_seconds: float, *, clock: Clock = _utcnow) -> bool:
        now = clock()
        return (
            InterviewOperation.update(
                status=OperationStatus.RETRY_WAIT.value,
                error_code=code,
                error_class=error_class,
                next_retry_at=now + timedelta(seconds=max(0.0, delay_seconds)),
                lease_owner=None,
                lease_expires_at=None,
                stage_deadline_at=None,
                **_touch(),
            )
            .where(
                (InterviewOperation.id == operation_id)
                & (InterviewOperation.status == OperationStatus.RUNNING.value)
                & (InterviewOperation.lease_owner == owner)
            )
            .execute()
            == 1
        )

    @staticmethod
    def fail(operation_id: str, owner: str, code: str, error_class: str, *, clock: Clock = _utcnow) -> bool:
        now = clock()
        changed = InterviewOperation.update(
            status=OperationStatus.FAILED.value,
            current_stage="failed",
            error_code=code,
            error_class=error_class,
            payload={},
            lease_owner=None,
            lease_expires_at=None,
            stage_deadline_at=None,
            completed_at=now,
            **_touch(),
        ).where(
            (InterviewOperation.id == operation_id)
            & (InterviewOperation.status == OperationStatus.RUNNING.value)
            & (InterviewOperation.lease_owner == owner)
        ).execute()
        if changed:
            InterviewRequest.update(
                status="failed",
                response={"error": {"code": code, "http_status": 409}},
                **_touch(),
            ).where(InterviewRequest.operation_id == operation_id).execute()
        return changed == 1

    @staticmethod
    def cancel_running(operation_id: str, owner: str, reason: str = "user_abort", *, clock: Clock = _utcnow) -> bool:
        now = clock()
        changed = InterviewOperation.update(
            status=OperationStatus.CANCELLED.value,
            current_stage="cancelled",
            cancellation_requested=True,
            cancellation_reason=reason[:64],
            payload={},
            lease_owner=None,
            lease_expires_at=None,
            stage_deadline_at=None,
            completed_at=now,
            **_touch(),
        ).where(
            (InterviewOperation.id == operation_id)
            & (InterviewOperation.status == OperationStatus.RUNNING.value)
            & (InterviewOperation.lease_owner == owner)
        ).execute()
        if changed:
            InterviewRequest.update(status="cancelled", response={"error": {"code": "operation_cancelled"}}, **_touch()).where(
                InterviewRequest.operation_id == operation_id
            ).execute()
        return changed == 1

    @staticmethod
    def cancel_session(session_id: str, reason: str = "user_abort", *, clock: Clock = _utcnow) -> int:
        now = clock()
        with DB.atomic():
            cancelled = InterviewOperation.update(
                status=OperationStatus.CANCELLED.value,
                current_stage="cancelled",
                cancellation_requested=True,
                cancellation_reason=reason[:64],
                payload={},
                completed_at=now,
                lease_owner=None,
                lease_expires_at=None,
                **_touch(),
            ).where(
                (InterviewOperation.session_id == session_id)
                & (InterviewOperation.status.in_((OperationStatus.PENDING.value, OperationStatus.RETRY_WAIT.value)))
            ).execute()
            running = InterviewOperation.update(
                cancellation_requested=True,
                cancellation_reason=reason[:64],
                **_touch(),
            ).where(
                (InterviewOperation.session_id == session_id)
                & (InterviewOperation.status == OperationStatus.RUNNING.value)
            ).execute()
            InterviewRequest.update(status="cancelled", response={"error": {"code": "operation_cancelled"}}, **_touch()).where(
                (InterviewRequest.session_id == session_id)
                & (InterviewRequest.status.in_(("queued", "processing")))
            ).execute()
        return cancelled + running

    @staticmethod
    def append_event(operation_id: str, operation_sequence: int, event_type: str, payload: dict[str, Any]) -> InterviewEvent:
        existing = InterviewEvent.get_or_none(
            (InterviewEvent.operation_id == operation_id) & (InterviewEvent.operation_sequence == operation_sequence)
        )
        if existing:
            return existing
        operation = InterviewOperation.get_by_id(operation_id)
        cleaned = public_event_payload(event_type, payload)
        for _ in range(5):
            try:
                with DB.atomic():
                    sequence = int(
                        InterviewEvent.select(fn.COALESCE(fn.MAX(InterviewEvent.sequence), 0))
                        .where(InterviewEvent.session_id == operation.session_id)
                        .scalar()
                        or 0
                    ) + 1
                    return InterviewEvent.create(
                        id=get_uuid(),
                        session_id=operation.session_id,
                        operation_id=operation.id,
                        operation_sequence=operation_sequence,
                        sequence=sequence,
                        event_type=event_type,
                        public_payload=cleaned,
                        **_timestamps(),
                    )
            except IntegrityError:
                existing = InterviewEvent.get_or_none(
                    (InterviewEvent.operation_id == operation_id) & (InterviewEvent.operation_sequence == operation_sequence)
                )
                if existing:
                    return existing
        raise DomainError("event_sequence_conflict", "Could not allocate an interview event sequence.", http_status=503)

    @staticmethod
    def append_worker_event(
        operation_id: str,
        owner: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        clock: Clock = _utcnow,
    ) -> InterviewEvent:
        """Atomically append the next public event and advance its checkpoint.

        Re-emitting the last exact event after a process crash is a replay, not
        a new event. The lease predicate fences a stale worker before either
        the event or checkpoint can be committed.
        """

        cleaned = public_event_payload(event_type, payload)
        for _ in range(5):
            try:
                with DB.atomic():
                    operation = InterviewOperation.get_or_none(
                        (InterviewOperation.id == operation_id)
                        & (InterviewOperation.status == OperationStatus.RUNNING.value)
                        & (InterviewOperation.lease_owner == owner)
                        & ~InterviewOperation.cancellation_requested
                    )
                    if operation is None:
                        raise DomainError("operation_lease_lost", "The operation lease was lost before event commit.", http_status=409)
                    last = (
                        InterviewEvent.select()
                        .where(InterviewEvent.operation_id == operation_id)
                        .order_by(InterviewEvent.operation_sequence.desc())
                        .first()
                    )
                    if last and last.event_type == event_type and dict(last.public_payload or {}) == cleaned:
                        return last
                    operation_sequence = int(last.operation_sequence if last else 0) + 1
                    sequence = int(
                        InterviewEvent.select(fn.COALESCE(fn.MAX(InterviewEvent.sequence), 0))
                        .where(InterviewEvent.session_id == operation.session_id)
                        .scalar()
                        or 0
                    ) + 1
                    event = InterviewEvent.create(
                        id=get_uuid(),
                        session_id=operation.session_id,
                        operation_id=operation.id,
                        operation_sequence=operation_sequence,
                        sequence=sequence,
                        event_type=event_type,
                        public_payload=cleaned,
                        **_timestamps(),
                    )
                    checkpoint = {
                        **dict(operation.checkpoint or {}),
                        "event_count": operation_sequence,
                        "last_event_type": event_type,
                    }
                    changed = InterviewOperation.update(
                        current_stage=event_type,
                        stage_deadline_at=clock() + timedelta(seconds=_positive_env("CS_INTERVIEW_STAGE_DEADLINE_SECONDS", 120)),
                        checkpoint=checkpoint,
                        **_touch(),
                    ).where(
                        (InterviewOperation.id == operation_id)
                        & (InterviewOperation.status == OperationStatus.RUNNING.value)
                        & (InterviewOperation.lease_owner == owner)
                        & ~InterviewOperation.cancellation_requested
                    ).execute()
                    if changed != 1:
                        raise DomainError("operation_lease_lost", "The operation lease was lost before event commit.", http_status=409)
                    return event
            except IntegrityError:
                continue
        raise DomainError("event_sequence_conflict", "Could not allocate an interview event sequence.", http_status=503)

    @staticmethod
    def list_events(session_id: str, after_sequence: int, *, operation_id: str | None = None, limit: int = 100) -> list[InterviewEvent]:
        query = InterviewEvent.select().where(
            (InterviewEvent.session_id == session_id) & (InterviewEvent.sequence > max(0, after_sequence))
        )
        if operation_id:
            query = query.where(InterviewEvent.operation_id == operation_id)
        return list(query.order_by(InterviewEvent.sequence.asc()).limit(max(1, min(limit, 200))))

    @staticmethod
    def cleanup(*, clock: Clock = _utcnow) -> dict[str, int]:
        now = clock()
        event_cutoff = now - timedelta(days=_positive_env("CS_INTERVIEW_EVENT_RETENTION_DAYS", 30))
        operation_cutoff = now - timedelta(days=_positive_env("CS_INTERVIEW_OPERATION_RETENTION_DAYS", 30))
        events = InterviewEvent.delete().where(InterviewEvent.create_time < int(event_cutoff.timestamp() * 1000)).execute()
        requests = InterviewRequest.delete().where(InterviewRequest.expires_at.is_null(False) & (InterviewRequest.expires_at < now)).execute()
        operations = InterviewOperation.delete().where(
            (InterviewOperation.status.in_(tuple(TERMINAL_OPERATION_STATUSES)))
            & (InterviewOperation.completed_at.is_null(False))
            & (InterviewOperation.completed_at < operation_cutoff)
        ).execute()
        return {"events": events, "requests": requests, "operations": operations}


def audit(tenant_id: str, actor_id: str, action: str, resource_type: str, resource_id: str, outcome: str, metadata: dict[str, Any] | None = None) -> InterviewAuditLog:
    return InterviewAuditLog.create(
        id=get_uuid(),
        tenant_id=tenant_id,
        actor_id_hash=hashlib.sha256(actor_id.encode("utf-8")).hexdigest(),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        metadata=_clean_public(metadata or {}),
        **_timestamps(),
    )


def operation_is_cancelled(operation_id: str) -> bool:
    operation = InterviewOperation.get_or_none(InterviewOperation.id == operation_id)
    return operation is None or operation.status == OperationStatus.CANCELLED.value or bool(operation.cancellation_requested)


def session_operation_counts(tenant_id: str) -> dict[str, int]:
    rows = (
        InterviewOperation.select(InterviewOperation.status, fn.COUNT(InterviewOperation.id).alias("count"))
        .where(InterviewOperation.tenant_id == tenant_id)
        .group_by(InterviewOperation.status)
    )
    return {row.status: int(row.count) for row in rows}


def record_model_call(**values: Any) -> InterviewModelCall:
    return InterviewModelCall.create(id=get_uuid(), **values, **_timestamps())


def load_external_checkpoint(operation_id: str, checkpoint_key: str) -> dict[str, Any] | None:
    row = InterviewOperationCheckpoint.get_or_none(
        (InterviewOperationCheckpoint.operation_id == operation_id)
        & (InterviewOperationCheckpoint.checkpoint_key == checkpoint_key)
    )
    return dict(row.value or {}) if row else None


def store_external_checkpoint(
    operation_id: str,
    lease_owner: str,
    checkpoint_key: str,
    stage: str,
    value: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Persist an external result only while the caller still owns the lease.

    The unique operation/key constraint turns a concurrent retry into a replay.
    The caller should wrap this together with usage accounting in ``DB.atomic``.
    """

    existing = load_external_checkpoint(operation_id, checkpoint_key)
    if existing is not None:
        return existing, False
    operation = InterviewOperation.get_or_none(
        (InterviewOperation.id == operation_id)
        & (InterviewOperation.status == OperationStatus.RUNNING.value)
        & (InterviewOperation.lease_owner == lease_owner)
        & ~InterviewOperation.cancellation_requested
    )
    if operation is None:
        raise DomainError("operation_lease_lost", "The operation lease was lost before checkpoint commit.", http_status=409)
    try:
        InterviewOperationCheckpoint.create(
            id=get_uuid(),
            operation_id=operation_id,
            checkpoint_key=checkpoint_key,
            stage=stage,
            value=value,
            **_timestamps(),
        )
        return value, True
    except IntegrityError:
        existing = load_external_checkpoint(operation_id, checkpoint_key)
        if existing is None:
            raise
        return existing, False
