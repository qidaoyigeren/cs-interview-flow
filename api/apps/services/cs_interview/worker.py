"""Durable CS interview worker using DB leases and the shared Redis stream."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from api.apps.services.cs_interview.domain import DomainError
from api.apps.services.cs_interview.observability import (
    OPERATION_DURATION,
    OPERATION_QUEUE_DELAY,
    OPERATION_RETRY,
    OPERATION_STUCK,
    OperationContext,
    metric_attributes,
    operation_context,
    safe_log_context,
)
from api.apps.services.cs_interview.pipeline import RAGFlowRuntimeAdapter
from api.apps.services.cs_interview.privacy import PrivacyService
from api.apps.services.cs_interview.quota import RedisQuotaManager
from api.apps.services.cs_interview.reliability import OperationStatus, OperationType, classify_failure, retry_delay_seconds
from api.apps.services.cs_interview.runtime import InstrumentedRuntimeAdapter, begin_runtime_attempt, end_runtime_attempt
from api.apps.services.cs_interview.service import InterviewApplication
from api.apps.services.cs_interview.tracing import TRACE_EMITTER
from api.db.db_models import InterviewOperation
from api.db.services.interview_operation_service import (
    InterviewOperationService,
    operation_is_cancelled,
    public_operation,
)
from api.db.services.interview_service import InterviewSessionRepository, public_session
from common.token_utils import langfuse_run_attrs

LOGGER = logging.getLogger(__name__)
QUEUE_NAME = "ragflow_cs_interview_operations"
CONSUMER_GROUP = "ragflow_cs_interview_workers"


def enqueue_operation(operation_id: str) -> bool:
    try:
        from rag.utils.redis_conn import REDIS_CONN

        return bool(REDIS_CONN.queue_product(QUEUE_NAME, {"operation_id": operation_id}))
    except Exception:  # noqa: BLE001 - the shared Redis wrapper exposes no stable exception hierarchy
        LOGGER.warning("CS interview operation wake-up enqueue failed", extra={"operation_id": operation_id, "error_type": "redis_unavailable"})
        return False


class InterviewOperationProcessor:
    def __init__(self, application: InterviewApplication | None = None, quota: RedisQuotaManager | None = None):
        self.quota = quota or RedisQuotaManager()
        if application is None:
            runtime = InstrumentedRuntimeAdapter(RAGFlowRuntimeAdapter(), self.quota)
            application = InterviewApplication(runtime=runtime)
        elif not isinstance(application.runtime, InstrumentedRuntimeAdapter):
            application.runtime = InstrumentedRuntimeAdapter(application.runtime, self.quota)
        self.application = application

    async def _append_events(self, operation: InterviewOperation, generator) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async for event in generator:
            InterviewOperationService.append_worker_event(
                operation.id,
                operation.lease_owner,
                event["event"],
                event["data"],
            )
            events.append(event)
            if operation_is_cancelled(operation.id):
                raise DomainError("operation_cancelled", "The operation was cancelled.", http_status=409)
        return events

    async def execute(self, operation: InterviewOperation) -> dict[str, Any]:
        payload = dict(operation.payload or {})
        session_snapshot = InterviewSessionRepository.get(
            operation.session_id,
            operation.tenant_id,
            operation.user_id,
        )
        context = OperationContext(
            tenant_id=operation.tenant_id,
            user_id=operation.user_id,
            session_id=operation.session_id,
            operation_id=operation.id,
            request_id=operation.request_id,
            lease_owner=operation.lease_owner or "",
            round_id=operation.round_id,
            prompt_version=str(session_snapshot.prompt_version),
            planner_version=str(session_snapshot.planner_version),
            knowledge_snapshot_version=str(session_snapshot.knowledge_base_versions or {}),
            runtime_config=dict((session_snapshot.model_config_snapshot or {}).get("experiment_variant") or {}),
        )
        token = operation_context.set(context)
        runtime_token = begin_runtime_attempt()
        trace_token = langfuse_run_attrs.set({"session_id": operation.session_id, "user_id": operation.user_id})
        try:
            InterviewOperationService.set_stage(operation.id, operation.lease_owner, "dispatch", {"dispatch_started": True})
            if operation.operation_type == OperationType.START_INTERVIEW.value:
                events = await self._append_events(
                    operation,
                    self.application.start_events(
                        operation.session_id,
                        operation.tenant_id,
                        operation.user_id,
                        operation.request_id,
                        int(payload["state_version"]),
                        operation_id=operation.id,
                    ),
                )
                session = InterviewSessionRepository.get(operation.session_id, operation.tenant_id, operation.user_id)
                return {"operation": public_operation(operation), "session": public_session(session), "event_count": len(events)}
            if operation.operation_type == OperationType.EVALUATE_ANSWER.value:
                events = await self._append_events(
                    operation,
                    self.application.answer_events(
                        operation.session_id,
                        operation.tenant_id,
                        operation.user_id,
                        payload["answer"],
                        operation.request_id,
                        int(payload["state_version"]),
                        operation_id=operation.id,
                    ),
                )
                session = InterviewSessionRepository.get(operation.session_id, operation.tenant_id, operation.user_id)
                return {"session": public_session(session), "event_count": len(events)}
            if operation.operation_type == OperationType.EXECUTE_CODE.value:
                limit = int(os.getenv("CS_INTERVIEW_GLOBAL_CODE_CONCURRENCY", "8"))
                with self.quota.semaphore("code", operation.id, limit, lease_seconds=120):
                    submission = await self.application.execute_code(
                        operation.session_id,
                        operation.tenant_id,
                        operation.user_id,
                        payload["language"],
                        payload["source_code"],
                        hidden=bool(payload["hidden"]),
                        request_id=operation.request_id,
                        operation_id=operation.id,
                    )
                InterviewOperationService.append_worker_event(
                    operation.id,
                    operation.lease_owner,
                    "code_completed",
                    {"submission": submission},
                )
                return {"submission": submission, "event_count": 1}
            raise DomainError("invalid_operation_type", "No worker handler exists for this operation type.")
        finally:
            # Trace events are buffered in memory and flushed here, best-effort,
            # so a failed trace write can never affect the operation result.
            TRACE_EMITTER.flush()
            end_runtime_attempt(runtime_token)
            langfuse_run_attrs.reset(trace_token)
            operation_context.reset(token)


class InterviewWorker:
    def __init__(self, owner: str | None = None, processor: InterviewOperationProcessor | None = None):
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.processor = processor or InterviewOperationProcessor()
        self.lease_seconds = max(5, int(os.getenv("CS_INTERVIEW_OPERATION_LEASE_SECONDS", "30")))
        self.stop = asyncio.Event()
        self.wake = asyncio.Event()
        self.guard_errors: dict[str, DomainError] = {}

    async def _consume_wakeups(self) -> None:
        """Use the existing Redis stream for latency only; the DB remains authoritative."""

        from rag.utils.redis_conn import REDIS_CONN

        while not self.stop.is_set():
            try:
                message = await asyncio.to_thread(
                    REDIS_CONN.queue_consumer,
                    QUEUE_NAME,
                    CONSUMER_GROUP,
                    self.owner,
                )
                if message:
                    message.ack()
                    self.wake.set()
            except Exception:  # noqa: BLE001 - the DB poller must survive Redis/client implementation failures
                LOGGER.warning("CS interview wake-up consumer unavailable", extra={"error_type": "redis_unavailable"})
                await asyncio.sleep(1)

    async def _lease_guard(self, operation_id: str, task: asyncio.Task) -> None:
        while not task.done() and not self.stop.is_set():
            await asyncio.sleep(max(1, self.lease_seconds // 3))
            operation = InterviewOperation.get_or_none(InterviewOperation.id == operation_id)
            if operation is None:
                task.cancel()
                return
            if operation.cancellation_requested or operation.status == OperationStatus.CANCELLED.value:
                cancel = getattr(self.processor.application.runner, "cancel", None)
                if cancel:
                    try:
                        await cancel(operation_id)
                    except Exception:  # noqa: BLE001 - cancellation adapters have provider-specific failures
                        LOGGER.warning("Runner cancellation request failed", extra={"operation_id": operation_id})
                task.cancel()
                return
            now = datetime.now(UTC).replace(tzinfo=None)
            if operation.stage_deadline_at and operation.stage_deadline_at <= now:
                self.guard_errors[operation_id] = DomainError(
                    "operation_stage_timeout",
                    "The current operation stage exceeded its deadline.",
                    http_status=504,
                )
                task.cancel()
                return
            if not InterviewOperationService.renew(operation_id, self.owner, lease_seconds=self.lease_seconds):
                task.cancel()
                return
            tenant_limit = int(os.getenv("CS_INTERVIEW_MAX_TENANT_RUNNING_OPERATIONS", "8"))
            if not self.processor.quota.acquire_semaphore(
                f"tenant-operation:{operation.tenant_id}",
                operation.id,
                tenant_limit,
                lease_seconds=self.lease_seconds,
            ):
                self.guard_errors[operation_id] = DomainError(
                    "operation_concurrency_lease_lost",
                    "The operation concurrency lease was lost.",
                    http_status=503,
                )
                task.cancel()
                return

    async def process(self, operation: InterviewOperation) -> None:
        started = time.perf_counter()
        queue_delay = max(0.0, (datetime.now(UTC).replace(tzinfo=None) - operation.create_date).total_seconds()) if isinstance(operation.create_date, datetime) else 0.0
        OPERATION_QUEUE_DELAY.record(queue_delay, metric_attributes(operation_type=operation.operation_type))
        context = OperationContext(
            tenant_id=operation.tenant_id,
            user_id=operation.user_id,
            session_id=operation.session_id,
            operation_id=operation.id,
            request_id=operation.request_id,
            lease_owner=operation.lease_owner or "",
            round_id=operation.round_id,
        )
        LOGGER.info("CS interview operation claimed", extra=safe_log_context(context, operation_type=operation.operation_type, attempt_count=operation.attempt_count))
        task = asyncio.create_task(self.processor.execute(operation))
        guard = asyncio.create_task(self._lease_guard(operation.id, task))
        try:
            remaining = max(0.1, (operation.deadline_at - datetime.now(UTC).replace(tzinfo=None)).total_seconds())
            result = await asyncio.wait_for(task, timeout=remaining)
            if operation_is_cancelled(operation.id):
                InterviewOperationService.cancel_running(operation.id, self.owner)
                return
            if not InterviewOperationService.complete(operation.id, self.owner, result):
                raise DomainError("operation_lease_lost", "The operation lease was lost before completion.", http_status=409)
            OPERATION_DURATION.record(time.perf_counter() - started, metric_attributes(operation_type=operation.operation_type, status="completed"))
        except asyncio.CancelledError:
            guard_error = self.guard_errors.pop(operation.id, None)
            if guard_error is not None:
                await self._handle_failure(operation, guard_error, guard_error)
            elif operation_is_cancelled(operation.id):
                InterviewOperationService.cancel_running(operation.id, self.owner)
        except TimeoutError as exc:
            await self._handle_failure(operation, DomainError("operation_deadline_exceeded", "The operation deadline was exceeded.", http_status=504), exc)
        except Exception as error:  # noqa: BLE001 - classification is centralized below
            await self._handle_failure(operation, error, error)
        finally:
            guard.cancel()
            await asyncio.gather(guard, return_exceptions=True)

    async def _handle_failure(self, operation: InterviewOperation, error: BaseException, original: BaseException) -> None:
        decision = classify_failure(error)
        refreshed = InterviewOperation.get_by_id(operation.id)
        if refreshed.cancellation_requested:
            InterviewOperationService.cancel_running(operation.id, self.owner)
            return
        if refreshed.status != OperationStatus.RUNNING.value or refreshed.lease_owner != self.owner:
            LOGGER.warning(
                "Ignoring failure from a worker that no longer owns the operation lease",
                extra={"operation_id": operation.id, "error_type": decision.code},
            )
            return
        can_retry = decision.retryable and refreshed.attempt_count < refreshed.max_attempts and refreshed.deadline_at > datetime.now(UTC).replace(tzinfo=None)
        if can_retry:
            delay = retry_delay_seconds(refreshed.attempt_count)
            if not InterviewOperationService.retry(operation.id, self.owner, decision.code, decision.error_class, delay):
                return
            OPERATION_RETRY.add(1, metric_attributes(operation_type=operation.operation_type, error_code=decision.code))
            enqueue_operation(operation.id)
            return
        try:
            InterviewOperationService.append_event(
                operation.id,
                10_000,
                "error",
                {"type": decision.code, "message": "The interview operation failed safely.", "status": 409, "retryable": False},
            )
        except Exception:
            LOGGER.exception("Could not persist terminal operation error event", extra={"operation_id": operation.id})
        if not InterviewOperationService.fail(operation.id, self.owner, decision.code, decision.error_class):
            return
        if operation.operation_type in {OperationType.START_INTERVIEW.value, OperationType.EVALUATE_ANSWER.value}:
            self.processor.application._fail_session(operation.session_id, operation.tenant_id, operation.user_id, decision.code)
        duration = 0.0
        if refreshed.started_at:
            duration = max(0.0, (datetime.now(UTC).replace(tzinfo=None) - refreshed.started_at).total_seconds())
        OPERATION_DURATION.record(duration, metric_attributes(operation_type=operation.operation_type, status="failed", error_code=decision.code))
        LOGGER.error("CS interview operation failed", extra=safe_log_context(
            OperationContext(
                tenant_id=operation.tenant_id,
                user_id=operation.user_id,
                session_id=operation.session_id,
                operation_id=operation.id,
                request_id=operation.request_id,
                lease_owner=operation.lease_owner or "",
                round_id=operation.round_id,
            ),
            error_code=decision.code,
            error_class=decision.error_class,
        ))

    async def run_once(self) -> bool:
        operation = InterviewOperationService.claim(self.owner, lease_seconds=self.lease_seconds)
        if operation is None:
            return False
        if operation.attempt_count > 1:
            OPERATION_STUCK.add(1, metric_attributes(operation_type=operation.operation_type, status="reclaimed"))
        tenant_limit = int(os.getenv("CS_INTERVIEW_MAX_TENANT_RUNNING_OPERATIONS", "8"))
        try:
            with self.processor.quota.semaphore(f"tenant-operation:{operation.tenant_id}", operation.id, tenant_limit, lease_seconds=self.lease_seconds):
                await self.process(operation)
        except DomainError as error:
            await self._handle_failure(operation, error, error)
        return True

    async def run(self) -> None:
        last_cleanup = 0.0
        queue_task = asyncio.create_task(self._consume_wakeups())
        try:
            while not self.stop.is_set():
                worked = await self.run_once()
                now = time.monotonic()
                if now - last_cleanup >= 3600:
                    InterviewOperationService.cleanup()
                    PrivacyService.cleanup()
                    try:
                        from api.apps.services.cs_interview.experiment_service import auto_stop_breached

                        auto_stop_breached()
                    except Exception:  # guardrail auto-stop must never kill the worker loop
                        LOGGER.exception("CS interview experiment guardrail check failed")
                    last_cleanup = now
                if not worked:
                    self.wake.clear()
                    stop_wait = asyncio.create_task(self.stop.wait())
                    wake_wait = asyncio.create_task(self.wake.wait())
                    done, pending = await asyncio.wait(
                        {stop_wait, wake_wait},
                        timeout=0.5,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in (*done, *pending):
                        task.cancel()
                    await asyncio.gather(*done, *pending, return_exceptions=True)
        finally:
            queue_task.cancel()
            await asyncio.gather(queue_task, return_exceptions=True)


async def _main() -> None:
    parser = argparse.ArgumentParser(description="CS interview durable operation worker")
    parser.add_argument("--owner", default=None)
    args = parser.parse_args()
    worker = InterviewWorker(owner=args.owner)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop.set)
        except NotImplementedError:  # Windows development only
            pass
    await worker.run()


if __name__ == "__main__":
    asyncio.run(_main())
