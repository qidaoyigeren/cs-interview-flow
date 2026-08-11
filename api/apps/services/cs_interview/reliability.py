"""Failure policy and bounded retry primitives for durable interview work."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import StrEnum

from api.apps.services.cs_interview.domain import DomainError


class OperationType(StrEnum):
    START_INTERVIEW = "start_interview"
    PREPARE_QUESTION = "prepare_question"
    EVALUATE_ANSWER = "evaluate_answer"
    GENERATE_FOLLOWUP = "generate_followup"
    PREPARE_NEXT_QUESTION = "prepare_next_question"
    GENERATE_REPORT = "generate_report"
    EXECUTE_CODE = "execute_code"


class OperationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_OPERATION_STATUSES = {
    OperationStatus.COMPLETED.value,
    OperationStatus.FAILED.value,
    OperationStatus.CANCELLED.value,
}

RETRYABLE_ERROR_CODES = {
    "llm_rate_limited",
    "llm_server_error",
    "llm_timeout",
    "network_timeout",
    "retrieval_failed",
    "retrieval_timeout",
    "quota_backend_unavailable",
    "database_unavailable",
    "redis_unavailable",
    "runner_unavailable",
    "runner_busy",
    "operation_stage_timeout",
    "dependency_circuit_open",
    "question_generation_failed",
    "evaluation_failed",
}

NON_RETRYABLE_ERROR_CODES = {
    "insufficient_evidence",
    "no_eligible_topic",
    "invalid_profile",
    "invalid_session",
    "invalid_question",
    "invalid_judge_output",
    "invalid_answer_state",
    "invalid_followup",
    "state_conflict",
    "session_terminal",
    "operation_cancelled",
    "ungrounded_question",
    "question_answer_leakage",
    "followup_leakage",
    "jd_irrelevant_question",
    "code_question_preflight_failed",
    "token_budget_exhausted",
    "cost_budget_exhausted",
    "llm_call_budget_exhausted",
    "retrieval_budget_exhausted",
    "cost_unknown",
    # Project deep-dive deterministic gates: these are handled locally (retry
    # retrieval / downgrade to foundation), never by the operation retry loop.
    "project_evidence_irrelevant",
    "project_question_unbound",
    "invalid_project_contract",
}


@dataclass(frozen=True)
class FailureDecision:
    retryable: bool
    code: str
    error_class: str


def classify_failure(error: BaseException) -> FailureDecision:
    if isinstance(error, DomainError):
        if error.code in NON_RETRYABLE_ERROR_CODES:
            return FailureDecision(False, error.code, type(error).__name__)
        if error.code in RETRYABLE_ERROR_CODES or error.http_status in {429, 502, 503, 504}:
            return FailureDecision(True, error.code, type(error).__name__)
        return FailureDecision(False, error.code, type(error).__name__)
    name = type(error).__name__
    response = getattr(error, "response", None)
    status_code = getattr(error, "status_code", None) or getattr(response, "status_code", None)
    if status_code == 429:
        return FailureDecision(True, "llm_rate_limited", name)
    if isinstance(status_code, int) and status_code >= 500:
        return FailureDecision(True, "llm_server_error", name)
    lowered = name.lower()
    retryable = any(part in lowered for part in ("timeout", "connection", "operational", "interface"))
    return FailureDecision(retryable, "transient_dependency_error" if retryable else "internal_error", name)


def normalize_llm_failure(error: BaseException) -> DomainError:
    decision = classify_failure(error)
    if decision.code == "llm_rate_limited":
        return DomainError(decision.code, "The model provider rate limit was reached.", http_status=503)
    if decision.code in {"llm_server_error", "transient_dependency_error"}:
        return DomainError(decision.code, "The model provider is temporarily unavailable.", http_status=503)
    return DomainError("llm_request_failed", "The model request failed safely.", http_status=502)


def retry_delay_seconds(attempt_count: int, *, base: float = 1.0, maximum: float = 60.0, jitter: float = 0.25, random_source=None) -> float:
    source = random_source or random.random
    bounded = min(maximum, base * (2 ** max(0, attempt_count - 1)))
    return bounded * (1 - jitter + source() * jitter * 2)
