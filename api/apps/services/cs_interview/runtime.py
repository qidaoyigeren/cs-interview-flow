"""Timeout, quota, usage, and trace wrapper around the owning RAGFlow runtime."""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import os
import time
from typing import Any

from api.apps.services.cs_interview.domain import DomainError
from api.apps.services.cs_interview.observability import (
    LLM_ESTIMATED_COST,
    LLM_LATENCY,
    LLM_REQUEST,
    LLM_TOKEN,
    RETRIEVAL_LATENCY,
    RETRIEVAL_ZERO_RESULT,
    metric_attributes,
    operation_context,
)
from api.apps.services.cs_interview.pipeline import RuntimeAdapter
from api.apps.services.cs_interview.quota import BudgetService, RedisQuotaManager, estimate_model_cost
from api.apps.services.cs_interview.reliability import normalize_llm_failure
from api.apps.services.cs_interview.tracing import TRACE_EMITTER, TraceEventKind
from api.db.db_models import DB
from api.db.services.interview_operation_service import load_external_checkpoint, record_model_call, store_external_checkpoint
from common.token_utils import num_tokens_from_string


def _stage_from_prompt(system: str) -> str:
    if "grounded question generator" in system:
        return "generate_question"
    if "technical interview judge" in system:
        return "judge"
    if "extract interview state" in system:
        return "extract_answer_state"
    if "interview follow-up" in system:
        return "generate_followup"
    return "model_call"


def _configured_temperature(context, stage: str, requested: float) -> float:
    if context is None:
        return requested
    config = context.runtime_config or {}
    per_stage = config.get("temperatures")
    configured = per_stage.get(stage, config.get("temperature")) if isinstance(per_stage, dict) else config.get("temperature")
    if isinstance(configured, (int, float)) and not isinstance(configured, bool):
        return float(configured)
    return requested


def _emit_model_trace(
    context,
    *,
    stage: str,
    status: str,
    model: str = "",
    latency_ms: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    estimated_cost: float | None = None,
    error_code: str | None = None,
) -> None:
    if context is None:
        return
    TRACE_EMITTER.emit(
        TraceEventKind.MODEL_CALL_COMPLETED.value if status == "completed" else TraceEventKind.MODEL_CALL_FAILED.value,
        session_id=context.session_id,
        tenant_id=context.tenant_id,
        round_id=context.round_id,
        operation_id=context.operation_id,
        status="succeeded" if status == "completed" else "failed",
        duration_ms=latency_ms,
        error_code=error_code,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        estimated_cost=estimated_cost,
        metadata={"stage": stage, "model": model, "error_code": error_code},
    )


_call_ordinals: contextvars.ContextVar[dict[str, int] | None] = contextvars.ContextVar(
    "cs_interview_runtime_call_ordinals", default=None
)


def begin_runtime_attempt():
    return _call_ordinals.set({})


def end_runtime_attempt(token) -> None:
    _call_ordinals.reset(token)


def _checkpoint_key(kind: str, stage: str, identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    base = f"{kind}:{stage}:{digest}"
    counters = _call_ordinals.get()
    if counters is None:
        counters = {}
        _call_ordinals.set(counters)
    ordinal = counters.get(base, 0) + 1
    counters[base] = ordinal
    return hashlib.sha256(f"{base}:{ordinal}".encode()).hexdigest()


class InstrumentedRuntimeAdapter:
    def __init__(self, delegate: RuntimeAdapter, quota: RedisQuotaManager | None = None):
        self.delegate = delegate
        self.quota = quota

    async def retrieve(self, tenant_id: str, dataset_id: str, query: str, config: dict[str, Any]) -> list[dict[str, Any]]:
        context = operation_context.get()
        checkpoint_key = _checkpoint_key("retrieval", "retrieve", f"{dataset_id}\0{query}\0{config!r}") if context else ""
        if context:
            checkpoint = load_external_checkpoint(context.operation_id, checkpoint_key)
            if checkpoint is not None:
                return list(checkpoint.get("result") or [])
        if context:
            BudgetService.reserve_operation_call(
                context.operation_id,
                "retrieval_calls",
                int(os.getenv("CS_INTERVIEW_MAX_RETRIEVALS_PER_OPERATION", "4")),
                "retrieval_budget_exhausted",
                lease_owner=context.lease_owner,
            )
            (self.quota or RedisQuotaManager()).check_circuit(f"retrieval:{context.tenant_id}")
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self.delegate.retrieve(tenant_id, dataset_id, query, config),
                timeout=float(os.getenv("CS_INTERVIEW_RETRIEVAL_TIMEOUT_SECONDS", "20")),
            )
        except TimeoutError as exc:
            if context:
                (self.quota or RedisQuotaManager()).record_dependency_failure(f"retrieval:{context.tenant_id}")
            raise DomainError("retrieval_timeout", "The retrieval stage timed out.", http_status=503) from exc
        except DomainError:
            raise
        except Exception as exc:
            if context:
                (self.quota or RedisQuotaManager()).record_dependency_failure(f"retrieval:{context.tenant_id}")
            raise DomainError("retrieval_failed", "The retrieval service is temporarily unavailable.", http_status=503) from exc
        elapsed = time.perf_counter() - started
        if context:
            (self.quota or RedisQuotaManager()).record_dependency_success(f"retrieval:{context.tenant_id}")
        RETRIEVAL_LATENCY.record(elapsed, metric_attributes(stage="retrieve", status="completed"))
        if not result:
            RETRIEVAL_ZERO_RESULT.add(1, metric_attributes(stage="retrieve"))
        if context:
            with DB.atomic():
                persisted, created = store_external_checkpoint(
                    context.operation_id,
                    context.lease_owner,
                    checkpoint_key,
                    "retrieve",
                    {"result": result},
                )
                if created:
                    BudgetService.record_retrieval(context.session_id)
                else:
                    result = list(persisted.get("result") or [])
        return result

    async def chat(self, tenant_id: str, system: str, user: str, *, temperature: float = 0.1) -> tuple[str, str]:
        context = operation_context.get()
        stage = _stage_from_prompt(system)
        temperature = _configured_temperature(context, stage, temperature)
        checkpoint_key = _checkpoint_key(
            "llm",
            stage,
            f"{system}\0{user}\0{temperature}",
        ) if context else ""
        if context:
            checkpoint = load_external_checkpoint(context.operation_id, checkpoint_key)
            if checkpoint is not None:
                return str(checkpoint.get("output") or ""), str(checkpoint.get("model") or "")
        prompt_tokens_estimate = num_tokens_from_string(system) + num_tokens_from_string(user)
        if context:
            BudgetService.reserve_operation_call(
                context.operation_id,
                "llm_calls",
                int(os.getenv("CS_INTERVIEW_MAX_LLM_CALLS_PER_OPERATION", "8")),
                "llm_call_budget_exhausted",
                lease_owner=context.lease_owner,
            )
            BudgetService.check_before_llm(context.session_id, prompt_tokens_estimate)
            quota = self.quota or RedisQuotaManager()
            quota.check_llm_rate(context.tenant_id)
            quota.check_circuit(f"llm:{context.tenant_id}")
        started = time.perf_counter()
        try:
            timeout = float(os.getenv("CS_INTERVIEW_LLM_TIMEOUT_SECONDS", "60"))
            if context and stage == "judge":
                quota = self.quota or RedisQuotaManager()
                limit = int(os.getenv("CS_INTERVIEW_GLOBAL_JUDGE_CONCURRENCY", "16"))
                with quota.semaphore("judge", f"{context.operation_id}:judge", limit, lease_seconds=int(timeout) + 10):
                    output, model = await asyncio.wait_for(
                        self.delegate.chat(tenant_id, system, user, temperature=temperature),
                        timeout=timeout,
                    )
            else:
                output, model = await asyncio.wait_for(
                    self.delegate.chat(tenant_id, system, user, temperature=temperature),
                    timeout=timeout,
                )
            status = "completed"
            error_class = None
            if context:
                (self.quota or RedisQuotaManager()).record_dependency_success(f"llm:{context.tenant_id}")
        except TimeoutError as exc:
            status = "failed"
            error_class = type(exc).__name__
            if context:
                record_model_call(
                    tenant_id=context.tenant_id,
                    session_id=context.session_id,
                    operation_id=context.operation_id,
                    round_id=context.round_id,
                    stage=stage,
                    model="",
                    prompt_version=context.prompt_version,
                    prompt_snapshot={"system": system, "user": user, "temperature": temperature},
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    estimated_cost=None,
                    cost_unknown=True,
                    status=status,
                    error_class=error_class,
                )
                (self.quota or RedisQuotaManager()).record_dependency_failure(f"llm:{context.tenant_id}")
                _emit_model_trace(
                    context,
                    stage=stage,
                    status=status,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    error_code="llm_timeout",
                )
            raise DomainError("llm_timeout", "The model stage timed out.", http_status=503) from exc
        except DomainError as exc:
            if context:
                latency_ms = int((time.perf_counter() - started) * 1000)
                record_model_call(
                    tenant_id=context.tenant_id,
                    session_id=context.session_id,
                    operation_id=context.operation_id,
                    round_id=context.round_id,
                    stage=stage,
                    model="",
                    prompt_version=context.prompt_version,
                    prompt_snapshot={"system": system, "user": user, "temperature": temperature},
                    latency_ms=latency_ms,
                    estimated_cost=None,
                    cost_unknown=True,
                    status="failed",
                    error_class=type(exc).__name__,
                )
                _emit_model_trace(
                    context,
                    stage=stage,
                    status="failed",
                    latency_ms=latency_ms,
                    error_code=exc.code,
                )
            raise
        except Exception as exc:
            error_class = type(exc).__name__
            if context:
                record_model_call(
                    tenant_id=context.tenant_id,
                    session_id=context.session_id,
                    operation_id=context.operation_id,
                    round_id=context.round_id,
                    stage=stage,
                    model="",
                    prompt_version=context.prompt_version,
                    prompt_snapshot={"system": system, "user": user, "temperature": temperature},
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    estimated_cost=None,
                    cost_unknown=True,
                    status="failed",
                    error_class=error_class,
                )
                (self.quota or RedisQuotaManager()).record_dependency_failure(f"llm:{context.tenant_id}")
                _emit_model_trace(
                    context,
                    stage=stage,
                    status="failed",
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    error_code="llm_failed",
                )
            raise normalize_llm_failure(exc) from exc
        latency = time.perf_counter() - started
        usage = getattr(self.delegate, "last_usage", {}) or {}
        prompt_tokens = int(usage.get("prompt_tokens") or prompt_tokens_estimate)
        completion_tokens = int(usage.get("completion_tokens") or num_tokens_from_string(output))
        estimated_cost = estimate_model_cost(model, prompt_tokens, completion_tokens)
        attributes = metric_attributes(stage=stage, status=status, model=model)
        LLM_REQUEST.add(1, attributes)
        LLM_LATENCY.record(latency, attributes)
        LLM_TOKEN.add(prompt_tokens + completion_tokens, attributes)
        if estimated_cost is not None:
            LLM_ESTIMATED_COST.add(estimated_cost, attributes)
        if context:
            with DB.atomic():
                persisted, created = store_external_checkpoint(
                    context.operation_id,
                    context.lease_owner,
                    checkpoint_key,
                    stage,
                    {"output": output, "model": model},
                )
                if not created:
                    return str(persisted.get("output") or ""), str(persisted.get("model") or "")
                BudgetService.record_llm(context.session_id, prompt_tokens, completion_tokens, estimated_cost)
                record_model_call(
                    tenant_id=context.tenant_id,
                    session_id=context.session_id,
                    operation_id=context.operation_id,
                    round_id=context.round_id,
                    stage=stage,
                    model=model,
                    prompt_version=context.prompt_version,
                    prompt_snapshot={"system": system, "user": user, "temperature": temperature},
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=int(latency * 1000),
                    estimated_cost=estimated_cost,
                    cost_unknown=estimated_cost is None,
                    status=status,
                    error_class=error_class,
                )
            _emit_model_trace(
                context,
                stage=stage,
                status=status,
                model=model,
                latency_ms=int(latency * 1000),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost=estimated_cost,
            )
        return output, model

    async def embed(self, tenant_id: str, texts: list[str]) -> list[list[float]]:
        try:
            return await asyncio.wait_for(
                self.delegate.embed(tenant_id, texts),
                timeout=float(os.getenv("CS_INTERVIEW_LLM_TIMEOUT_SECONDS", "60")),
            )
        except TimeoutError as exc:
            raise DomainError("llm_timeout", "The embedding stage timed out.", http_status=503) from exc

    def model_snapshot(self, tenant_id: str) -> dict[str, Any]:
        return self.delegate.model_snapshot(tenant_id)
