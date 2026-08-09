"""SLO alert config, versioned pricing, and export formula-injection tests."""

from __future__ import annotations

import pytest

from api.apps.services.cs_interview.privacy import _formula_safe
from api.apps.services.cs_interview.quota import estimate_model_cost, get_pricing_config
from api.apps.services.cs_interview.slo import alert_rules, evaluate_alerts, tenant_budget_cents


def test_formula_safe_neutralizes_spreadsheet_formulas_recursively():
    payload = {
        "name": "normal value",
        "attack": "=SUM(A1:A9)",
        "plus": "+1+1",
        "tab_attack": "\t=cmd()",
        "nested": {"inner": "@import", "list": ["-2+3", "safe"]},
        "number": 42,
    }
    safe = _formula_safe(payload)
    assert safe["name"] == "normal value"
    assert safe["attack"].startswith("'")
    assert safe["plus"].startswith("'")
    assert safe["tab_attack"].startswith("'")
    assert safe["nested"]["inner"].startswith("'")
    assert safe["nested"]["list"][0].startswith("'")
    assert safe["nested"]["list"][1] == "safe"
    assert safe["number"] == 42


def test_formula_safe_keeps_single_character_cells():
    # A single "=" should not be prefixed (it is not an injection payload).
    assert _formula_safe("=") == "="


def test_pricing_config_is_versioned_and_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("CS_INTERVIEW_MODEL_PRICING_JSON", '{"model-a": {"prompt_per_million": 1.0, "completion_per_million": 2.0}}')
    version, pricing = get_pricing_config()
    assert version.startswith("env:")
    assert pricing["model-a"]["prompt_per_million"] == 1.0
    cost = estimate_model_cost("model-a", 1_000_000, 500_000)
    assert cost == pytest.approx(1.0 + 1.0)
    assert estimate_model_cost("unknown-model", 1, 1) is None


def test_alert_rules_cover_spec_slos_and_carry_runbooks(monkeypatch):
    monkeypatch.setenv("CS_INTERVIEW_RUNBOOK_SESSION_CREATED", "https://runbook.example/session-created")
    rules = {rule.name: rule for rule in alert_rules()}
    assert rules["session_created_success"].target == 0.999
    assert rules["answer_request_success"].level == "critical"
    assert rules["state_loss_rate"].operator == "=="
    assert rules["replay_inconsistency_ratio"].level == "critical"
    assert rules["first_question_p95_ms"].operator == "<="
    assert rules["judge_p95_ms"].target == 15_000
    assert rules["runner_failure_rate"].level == "critical"
    assert rules["cost_unknown_rate"].operator == "=="
    assert rules["session_created_success"].runbook == "https://runbook.example/session-created"
    # Runbook links never leak into low-cardinality metrics (they are config only).


def test_tenant_budget_cents_override(monkeypatch):
    monkeypatch.setenv("CS_INTERVIEW_TENANT_BUDGET_CENTS_TENANT_1", "500")
    monkeypatch.setenv("CS_INTERVIEW_MAX_SESSION_COST", "10.0")
    assert tenant_budget_cents("tenant-1") == 500
    assert tenant_budget_cents("tenant-2") == 1000


def test_alert_evaluation_reports_breaches_and_insufficient_samples():
    results = {
        item["name"]: item
        for item in evaluate_alerts(
            {
                "session_created_success": 0.998,
                "answer_request_success": 1.0,
                "state_loss_rate": 0.0,
                "duplicate_question_ratio": 0.01,
                "hidden_answer_leakage_count": 0,
                "replay_inconsistency_ratio": 0.0,
                "first_question_p95_ms": 16_000,
                "judge_p95_ms": None,
                "runner_failure_rate": 0.0,
                "cost_unknown_rate": 0.0,
            }
        )
    }
    assert results["session_created_success"]["breached"] is True
    assert results["first_question_p95_ms"]["breached"] is True
    assert results["answer_request_success"]["breached"] is False
    assert results["judge_p95_ms"]["insufficient"] is True
