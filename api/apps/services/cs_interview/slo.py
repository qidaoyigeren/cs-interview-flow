"""SLO targets, alert definitions and cost-control policy.

The default targets follow the Phase-3 spec.  Alert levels and runbook links
are configuration, not code: operators override the runbook base URL per alert
via ``CS_INTERVIEW_RUNBOOK_<NAME>``.  Cost control never silently lowers a
safety check -- on over-budget the request fails closed (see quota.BudgetService)
and only an alert is raised.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from api.apps.services.cs_interview.observability import STAGE_LATENCY, metric_attributes


@dataclass(frozen=True)
class AlertRule:
    name: str
    level: str  # warning | critical
    operator: str
    target: float
    runbook: str


def _env_runbook(name: str) -> str:
    return os.getenv(f"CS_INTERVIEW_RUNBOOK_{name.upper()}", f"https://ragflow.example/runbooks/cs-interview/{name}")


def alert_rules() -> list[AlertRule]:
    return [
        AlertRule("session_created_success", "critical", ">=", 0.999, _env_runbook("SESSION_CREATED")),
        AlertRule("answer_request_success", "critical", ">=", 0.995, _env_runbook("ANSWER_REQUEST")),
        AlertRule("state_loss_rate", "critical", "==", 0.0, _env_runbook("STATE_LOSS")),
        AlertRule("duplicate_question_ratio", "warning", "<", 0.02, _env_runbook("DUPLICATE_QUESTION")),
        AlertRule("hidden_answer_leakage_count", "critical", "==", 0.0, _env_runbook("HIDDEN_LEAK")),
        AlertRule("replay_inconsistency_ratio", "critical", "==", 0.0, _env_runbook("REPLAY")),
        AlertRule("first_question_p95_ms", "warning", "<=", 15_000.0, _env_runbook("FIRST_QUESTION_LATENCY")),
        AlertRule("judge_p95_ms", "warning", "<=", 15_000.0, _env_runbook("JUDGE_LATENCY")),
        AlertRule("runner_failure_rate", "critical", "<", 0.05, _env_runbook("RUNNER_FAILURE")),
        AlertRule("cost_unknown_rate", "warning", "==", 0.0, _env_runbook("COST_UNKNOWN")),
    ]


def evaluate_alerts(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate every configured rule; missing samples remain explicit."""
    evaluations: list[dict[str, Any]] = []
    for rule in alert_rules():
        value = metrics.get(rule.name)
        insufficient = not isinstance(value, (int, float)) or isinstance(value, bool)
        passed: bool | None = None
        if not insufficient:
            numeric = float(value)
            passed = {
                ">=": numeric >= rule.target,
                ">": numeric > rule.target,
                "<=": numeric <= rule.target,
                "<": numeric < rule.target,
                "==": numeric == rule.target,
            }.get(rule.operator)
        evaluations.append(
            {
                "name": rule.name,
                "level": rule.level,
                "operator": rule.operator,
                "target": rule.target,
                "value": value,
                "passed": passed,
                "breached": None if insufficient or passed is None else not passed,
                "insufficient": insufficient,
                "runbook": rule.runbook,
            }
        )
    return evaluations


def record_stage_latency(stage: str, duration_ms: int | None) -> None:
    """Record a per-stage latency histogram with low-cardinality labels."""
    if duration_ms is None or duration_ms < 0:
        return
    STAGE_LATENCY.record(duration_ms / 1000.0, attributes=metric_attributes(stage=stage))


def tenant_budget_cents(tenant_id: str) -> int:
    """Per-tenant, per-session cost budget in USD cents.

    Operators override the default via ``CS_INTERVIEW_TENANT_BUDGET_CENTS_<TENANT>``;
    the shared default is ``CS_INTERVIEW_MAX_SESSION_COST`` from quota.
    """
    tenant_key = f"CS_INTERVIEW_TENANT_BUDGET_CENTS_{''.join(ch if ch.isalnum() else '_' for ch in str(tenant_id)).upper()}"
    try:
        return int(os.getenv(tenant_key, ""))
    except ValueError:
        pass
    default_dollars = float(os.getenv("CS_INTERVIEW_MAX_SESSION_COST", "10.0"))
    return int(default_dollars * 100)
