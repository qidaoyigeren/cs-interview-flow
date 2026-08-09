"""Domain-specific interview experiments: stable bucketing and guardrails.

Not a general experiment platform. A variant binds prompt/planner versions,
retrieval config, models, temperature and feature flags. Traffic is split by a
stable hash of tenant/user/session, and a session is assigned exactly once at
creation -- it never switches variants mid-flight (the assignment row plus the
frozen session columns are authoritative).
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from api.apps.services.cs_interview.domain import (
    PLANNER_VERSION,
    PROMPT_VERSION,
    SUPPORTED_PLANNER_VERSIONS,
    DomainError,
)
from api.apps.services.cs_interview.pipeline import SUPPORTED_PROMPT_VERSIONS
from api.db.db_models import DB, InterviewExperiment, InterviewExperimentAssignment, InterviewOperation, InterviewTraceEvent
from api.db.services.interview_operation_service import audit
from api.db.services.interview_service import _touch
from common.misc_utils import get_uuid

_TEMPERATURE_STAGES = frozenset({"generate_question", "judge", "extract_answer_state", "generate_followup", "model_call"})
_FEATURE_FLAGS = frozenset({"semantic_dedup"})


def normalize_variant(raw: dict[str, Any] | None, *, default_variant_id: str) -> dict[str, Any]:
    """Validate and freeze only experiment controls that the runtime executes."""
    value = dict(raw or {})
    variant_id = str(value.get("variant_id") or default_variant_id).strip()
    if not variant_id or len(variant_id) > 64:
        raise DomainError("invalid_experiment_variant", "variant_id must be 1-64 characters.", http_status=400)
    prompt_version = str(value.get("prompt_version") or PROMPT_VERSION)
    planner_version = str(value.get("planner_version") or PLANNER_VERSION)
    if prompt_version not in SUPPORTED_PROMPT_VERSIONS:
        raise DomainError("unsupported_prompt_version", f"Prompt version {prompt_version} is not executable.", http_status=400)
    if planner_version not in SUPPORTED_PLANNER_VERSIONS:
        raise DomainError("unsupported_planner_version", f"Planner version {planner_version} is not executable.", http_status=400)

    result: dict[str, Any] = {
        "variant_id": variant_id,
        "prompt_version": prompt_version,
        "planner_version": planner_version,
    }
    for model_key in ("chat_model", "judge_model"):
        if value.get(model_key):
            result[model_key] = str(value[model_key]).strip()

    if "temperature" in value:
        temperature = value["temperature"]
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= float(temperature) <= 2:
            raise DomainError("invalid_experiment_variant", "temperature must be a number between 0 and 2.", http_status=400)
        result["temperature"] = float(temperature)
    if "temperatures" in value:
        temperatures = value["temperatures"]
        if not isinstance(temperatures, dict) or any(stage not in _TEMPERATURE_STAGES for stage in temperatures):
            raise DomainError("invalid_experiment_variant", "temperatures contains an unsupported model stage.", http_status=400)
        normalized_temperatures: dict[str, float] = {}
        for stage, temperature in temperatures.items():
            if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= float(temperature) <= 2:
                raise DomainError("invalid_experiment_variant", "Every stage temperature must be between 0 and 2.", http_status=400)
            normalized_temperatures[str(stage)] = float(temperature)
        result["temperatures"] = normalized_temperatures

    retrieval_config = value.get("retrieval_config")
    if retrieval_config is not None:
        if not isinstance(retrieval_config, dict):
            raise DomainError("invalid_experiment_variant", "retrieval_config must be an object.", http_status=400)
        result["retrieval_config"] = dict(retrieval_config)
    feature_flags = value.get("feature_flags")
    if feature_flags is not None:
        if not isinstance(feature_flags, dict) or any(name not in _FEATURE_FLAGS for name in feature_flags):
            raise DomainError("invalid_experiment_variant", "feature_flags contains an unsupported flag.", http_status=400)
        if any(not isinstance(enabled, bool) for enabled in feature_flags.values()):
            raise DomainError("invalid_experiment_variant", "Experiment feature flags must be booleans.", http_status=400)
        result["feature_flags"] = dict(feature_flags)
    return result


def stable_bucket(experiment_id: str, tenant_id: str, user_id: str, session_id: str) -> int:
    """Deterministic bucket in [0, 100) for traffic splitting."""
    digest = hashlib.sha256(f"{experiment_id}|{tenant_id}|{user_id}|{session_id}".encode()).hexdigest()[:8]
    return int(digest, 16) % 100


def active_experiments_for(tenant_id: str, *, now: datetime | None = None) -> list[InterviewExperiment]:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    query = InterviewExperiment.select().where(
        (InterviewExperiment.tenant_id == tenant_id)
        & (InterviewExperiment.status == "gray")
        & (InterviewExperiment.start_at.is_null(True) | (InterviewExperiment.start_at <= now))
        & (InterviewExperiment.end_at.is_null(True) | (InterviewExperiment.end_at >= now))
    ).order_by(InterviewExperiment.create_time.asc())
    results: list[InterviewExperiment] = []
    for row in query:
        targets = {str(item) for item in (row.target_tenants or [])}
        if not targets or tenant_id in targets:
            results.append(row)
    return results


def resolve_variant(
    tenant_id: str,
    user_id: str,
    session_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return and later persist a stable control or candidate assignment."""
    for experiment in active_experiments_for(tenant_id, now=now):
        bucket = stable_bucket(experiment.id, tenant_id, user_id, session_id)
        candidates = list(experiment.candidate_variants or [])
        use_candidate = bucket < int(experiment.traffic_percentage or 0) and bool(candidates)
        selected = candidates[bucket % len(candidates)] if use_candidate else experiment.control_variant
        variant = normalize_variant(dict(selected or {}), default_variant_id="control" if not use_candidate else "candidate")
        variant["experiment_id"] = experiment.id
        return variant
    return None


def assign(
    tenant_id: str,
    user_id: str,
    session_id: str,
    variant: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> None:
    if not variant or not variant.get("experiment_id"):
        return
    now = now or datetime.now(UTC).replace(tzinfo=None)
    experiment_id = str(variant["experiment_id"])
    with DB.atomic():
        existing = InterviewExperimentAssignment.get_or_none(InterviewExperimentAssignment.session_id == session_id)
        if existing:
            if existing.experiment_id != experiment_id or existing.variant_id != str(variant.get("variant_id") or "control"):
                raise DomainError("experiment_assignment_conflict", "The session already has a different experiment assignment.", http_status=409)
            return
        InterviewExperimentAssignment.create(
            id=get_uuid(), experiment_id=experiment_id, variant_id=str(variant.get("variant_id") or "control"),
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            bucket_hash=f"{stable_bucket(experiment_id, tenant_id, user_id, session_id):02d}", assigned_at=now,
        )


def _aggregate_guardrail_metric(metric: str, experiment_id: str, since: datetime) -> float:
    assignments = {
        row.session_id
        for row in InterviewExperimentAssignment.select().where(InterviewExperimentAssignment.experiment_id == experiment_id)
    }
    if not assignments:
        return 0.0
    failed = total = 0
    for row in InterviewTraceEvent.select().where(
        (InterviewTraceEvent.session_id.in_(assignments)) & (InterviewTraceEvent.occurred_at >= since)
    ):
        if row.event_type in {"session_completed", "session_failed"}:
            total += 1
            if row.event_type == "session_failed":
                failed += 1
    if metric == "session_failure_rate":
        return failed / total if total else 0.0
    if metric == "answer_request_failure_rate":
        operations = InterviewOperation.select().where(
            (InterviewOperation.session_id.in_(assignments))
            & (InterviewOperation.operation_type == "evaluate_answer")
            & (InterviewOperation.create_date >= since)
            & (InterviewOperation.status.in_(("completed", "failed", "cancelled")))
        )
        total = failed = 0
        for operation in operations:
            total += 1
            failed += int(operation.status == "failed")
        return failed / total if total else 0.0
    raise DomainError("unsupported_guardrail_metric", f"Guardrail metric {metric} is not supported.")


def guardrail_breaches(experiment: InterviewExperiment, *, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    window_hours = max(1, int(os.getenv("CS_INTERVIEW_GUARDRAIL_WINDOW_HOURS", "1")))
    since = now - timedelta(hours=window_hours)
    breaches: list[str] = []
    for rule in experiment.guardrail_metrics or []:
        metric = str(rule.get("metric") or "")
        operator = str(rule.get("operator") or ">=")
        try:
            target = float(rule.get("target") or 0)
        except (TypeError, ValueError):
            continue
        value = _aggregate_guardrail_metric(metric, experiment.id, since)
        if operator == ">=" and value >= target or operator == ">" and value > target or operator == "==" and value == target:
            breaches.append(metric)
    return breaches


def auto_stop_breached(*, now: datetime | None = None) -> list[str]:
    """Stop every active experiment whose guardrail metrics have deteriorated."""
    now = now or datetime.now(UTC).replace(tzinfo=None)
    stopped: list[str] = []
    for row in InterviewExperiment.select().where(InterviewExperiment.status == "gray"):
        breaches = guardrail_breaches(row, now=now)
        if not breaches:
            continue
        with DB.atomic():
            InterviewExperiment.update(status="stopped", **_touch()).where(InterviewExperiment.id == row.id).execute()
        audit(
            row.tenant_id,
            "guardrail-worker",
            "experiment_auto_stop",
            "interview_experiment",
            row.id,
            "stopped",
            {"breaches": breaches},
        )
        stopped.append(row.id)
    return stopped
