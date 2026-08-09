"""Shared Redis limits plus persistent interview token and cost budgets."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from typing import Any

from peewee import DatabaseError, fn

from api.apps.services.cs_interview.domain import DomainError
from api.apps.services.cs_interview.slo import tenant_budget_cents
from api.db.db_models import DB, InterviewOperation, InterviewPricingVersion, InterviewSession
from api.db.services.interview_service import _touch

LOGGER = logging.getLogger(__name__)

_SEMAPHORE_ACQUIRE = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local expires = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local owner = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZSCORE', key, owner) then
  redis.call('ZADD', key, expires, owner)
  redis.call('EXPIRE', key, math.ceil(expires - now) + 5)
  return 1
end
if redis.call('ZCARD', key) >= limit then return 0 end
redis.call('ZADD', key, expires, owner)
redis.call('EXPIRE', key, math.ceil(expires - now) + 5)
return 1
"""

_SEMAPHORE_RELEASE = """
return redis.call('ZREM', KEYS[1], ARGV[1])
"""


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


class RedisQuotaManager:
    def __init__(self, redis_db=None):
        if redis_db is None:
            from rag.utils.redis_conn import REDIS_CONN

            redis_db = REDIS_CONN
        self.redis_db = redis_db

    def _client(self):
        client = getattr(self.redis_db, "REDIS", None)
        if client is None:
            raise DomainError("quota_backend_unavailable", "The shared quota service is unavailable.", http_status=503)
        return client

    def token_bucket(self, key: str, capacity: int, *, window_seconds: int = 60, cost: int = 1) -> None:
        try:
            script = self.redis_db.lua_token_bucket
            result = script(
                keys=[f"cs-interview:quota:{key}"],
                args=[capacity, capacity / window_seconds, time.time(), cost],
                client=self._client(),
            )
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError("quota_backend_unavailable", "The shared quota service is unavailable.", http_status=503) from exc
        if int(result[0]) != 1:
            raise DomainError("rate_limited", "The distributed interview rate limit was reached.", http_status=429)

    def check_write_rate(self, user_id: str) -> None:
        self.token_bucket(f"user-write:{user_id}", _env_int("CS_INTERVIEW_USER_WRITES_PER_MINUTE", 30))

    def check_llm_rate(self, tenant_id: str) -> None:
        self.token_bucket(f"tenant-llm:{tenant_id}", _env_int("CS_INTERVIEW_TENANT_LLM_RATE_PER_MINUTE", 120))

    def check_circuit(self, dependency: str) -> None:
        try:
            if self._client().exists(f"cs-interview:circuit:open:{dependency}"):
                raise DomainError("dependency_circuit_open", "A required dependency is temporarily unavailable.", http_status=503)
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError("quota_backend_unavailable", "The shared quota service is unavailable.", http_status=503) from exc

    def record_dependency_failure(self, dependency: str) -> None:
        threshold = _env_int("CS_INTERVIEW_CIRCUIT_FAILURE_THRESHOLD", 5)
        window = _env_int("CS_INTERVIEW_CIRCUIT_WINDOW_SECONDS", 60)
        open_seconds = _env_int("CS_INTERVIEW_CIRCUIT_OPEN_SECONDS", 30)
        try:
            client = self._client()
            key = f"cs-interview:circuit:failures:{dependency}"
            failures = int(client.incr(key))
            if failures == 1:
                client.expire(key, window)
            if failures >= threshold:
                client.set(f"cs-interview:circuit:open:{dependency}", "1", ex=open_seconds)
        except Exception:  # noqa: BLE001 - optional circuit telemetry must never fail the request
            return

    def record_dependency_success(self, dependency: str) -> None:
        try:
            self._client().delete(f"cs-interview:circuit:failures:{dependency}")
        except Exception:  # noqa: BLE001 - optional circuit telemetry must never fail the request
            return

    def acquire_semaphore(self, name: str, owner: str, limit: int, *, lease_seconds: int = 120) -> bool:
        now = time.time()
        try:
            return bool(
                self._client().eval(
                    _SEMAPHORE_ACQUIRE,
                    1,
                    f"cs-interview:semaphore:{name}",
                    now,
                    now + lease_seconds,
                    limit,
                    owner,
                )
            )
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError("quota_backend_unavailable", "The shared quota service is unavailable.", http_status=503) from exc

    def release_semaphore(self, name: str, owner: str) -> None:
        try:
            self._client().eval(_SEMAPHORE_RELEASE, 1, f"cs-interview:semaphore:{name}", owner)
        except Exception:  # noqa: BLE001 - release is best effort after the protected work has completed
            return

    @contextmanager
    def semaphore(self, name: str, owner: str, limit: int, *, lease_seconds: int = 120):
        if not self.acquire_semaphore(name, owner, limit, lease_seconds=lease_seconds):
            raise DomainError("concurrency_limit", f"The {name} concurrency limit was reached.", http_status=429)
        try:
            yield
        finally:
            self.release_semaphore(name, owner)


class BudgetService:
    @staticmethod
    def check_before_llm(session_id: str, estimated_prompt_tokens: int) -> None:
        session = InterviewSession.get_by_id(session_id)
        maximum_tokens = _env_int("CS_INTERVIEW_MAX_SESSION_TOKENS", 100_000)
        maximum_cost = tenant_budget_cents(session.tenant_id) / 100.0
        if session.total_prompt_tokens + session.total_completion_tokens + estimated_prompt_tokens > maximum_tokens:
            raise DomainError("token_budget_exhausted", "The interview token budget has been exhausted.", http_status=409)
        if session.total_estimated_cost >= maximum_cost:
            raise DomainError("cost_budget_exhausted", "The interview cost budget has been exhausted.", http_status=409)
        if session.cost_unknown and os.getenv("CS_INTERVIEW_FAIL_ON_UNKNOWN_COST", "false").lower() == "true":
            raise DomainError("cost_unknown", "The configured model has no approved interview price.", http_status=409)

    @staticmethod
    def record_llm(session_id: str, prompt_tokens: int, completion_tokens: int, estimated_cost: float | None) -> None:
        values: dict[str, Any] = {
            "total_prompt_tokens": InterviewSession.total_prompt_tokens + max(0, prompt_tokens),
            "total_completion_tokens": InterviewSession.total_completion_tokens + max(0, completion_tokens),
            "llm_request_count": InterviewSession.llm_request_count + 1,
            **_touch(),
        }
        if estimated_cost is None:
            values["cost_unknown"] = True
        else:
            values["total_estimated_cost"] = InterviewSession.total_estimated_cost + max(0.0, estimated_cost)
        InterviewSession.update(**values).where(InterviewSession.id == session_id).execute()

    @staticmethod
    def reserve_operation_call(
        operation_id: str,
        key: str,
        maximum: int,
        error_code: str,
        *,
        lease_owner: str | None = None,
    ) -> int:
        condition = InterviewOperation.id == operation_id
        if lease_owner is not None:
            condition &= (InterviewOperation.status == "running") & (InterviewOperation.lease_owner == lease_owner)
        with DB.atomic():
            operation = InterviewOperation.get_or_none(condition)
            if operation is None:
                raise DomainError("operation_lease_lost", "The operation lease is no longer owned by this worker.", http_status=409)
            checkpoint = dict(operation.checkpoint or {})
            counters = dict(checkpoint.get("counters") or {})
            count = int(counters.get(key, 0)) + 1
            if count > maximum:
                raise DomainError(error_code, f"The operation {key.replace('_', ' ')} budget has been exhausted.", http_status=409)
            counters[key] = count
            checkpoint["counters"] = counters
            changed = InterviewOperation.update(checkpoint=checkpoint, **_touch()).where(condition).execute()
            if changed != 1:
                raise DomainError("operation_lease_lost", "The operation lease is no longer owned by this worker.", http_status=409)
        return count

    @staticmethod
    def record_retrieval(session_id: str) -> None:
        InterviewSession.update(
            retrieval_request_count=InterviewSession.retrieval_request_count + 1,
            **_touch(),
        ).where(InterviewSession.id == session_id).execute()


def get_pricing_config() -> tuple[str, dict[str, Any]]:
    """Return ``(version, pricing)`` from the active pricing row, else env JSON.

    Prices are never hardcoded in application code.  The active
    ``interview_pricing_version`` row wins when one exists; otherwise the
    ``CS_INTERVIEW_MODEL_PRICING_JSON`` env map is used with a content-derived
    version so cost estimates remain auditable across config changes.
    """
    try:
        active = (
            InterviewPricingVersion.select()
            .where(InterviewPricingVersion.active == True)
            .order_by(InterviewPricingVersion.create_time.desc())
            .first()
        )
        if active is not None and isinstance(active.pricing_json, dict) and active.pricing_json:
            return str(active.version), active.pricing_json
    except DatabaseError:  # pragma: no cover - supports pre-migration/offline processes
        LOGGER.warning("Interview pricing table unavailable; falling back to environment pricing")
    try:
        pricing = json.loads(os.getenv("CS_INTERVIEW_MODEL_PRICING_JSON", "{}"))
    except json.JSONDecodeError:
        pricing = {}
    version = "env:" + hashlib.sha256(json.dumps(pricing, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return version, pricing


def estimate_model_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    _version, pricing = get_pricing_config()
    entry = pricing.get(model)
    if not isinstance(entry, dict):
        return None
    try:
        prompt_rate = float(entry["prompt_per_million"])
        completion_rate = float(entry["completion_per_million"])
    except (KeyError, TypeError, ValueError):
        return None
    return (prompt_tokens * prompt_rate + completion_tokens * completion_rate) / 1_000_000


def active_operation_count(tenant_id: str) -> int:
    return int(
        InterviewOperation.select(fn.COUNT(InterviewOperation.id))
        .where((InterviewOperation.tenant_id == tenant_id) & (InterviewOperation.status.in_(("pending", "running", "retry_wait"))))
        .scalar()
        or 0
    )
