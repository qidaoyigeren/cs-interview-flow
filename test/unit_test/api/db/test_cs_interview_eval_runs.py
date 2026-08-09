"""Evaluation run persistence tests (no external services)."""

from __future__ import annotations

from pathlib import Path

import pytest
from peewee import SqliteDatabase

from api.apps.services.cs_interview.eval_runs import persist_run
from api.apps.services.cs_interview.evaluation import evaluate_file, evaluate_fixture
from api.db.db_models import (
    InterviewEvaluationMetric,
    InterviewEvaluationRun,
)

MODELS = (InterviewEvaluationRun, InterviewEvaluationMetric)
FIXTURE = Path("test/fixtures/cs_interview/offline_eval.json")


@pytest.fixture
def eval_db(monkeypatch):
    database = SqliteDatabase(":memory:")
    with database.bind_ctx(MODELS, bind_refs=False, bind_backrefs=False):
        database.create_tables(MODELS)
        from api.apps.services.cs_interview import eval_runs as eval_runs_module

        monkeypatch.setattr(eval_runs_module, "DB", database)
        yield database
    database.close()


def test_persist_run_writes_run_and_metric_rows(eval_db):
    result = evaluate_file(FIXTURE)
    assert result.passed
    run_id = persist_run(
        result,
        run_type="offline",
        fixture_version="offline_eval.json",
        planner_version="cs-interview-planner-v1",
        prompt_version="cs-interview-v1",
        created_by="ci",
    )
    run = InterviewEvaluationRun.get_by_id(run_id)
    assert run.passed is True
    assert run.run_type == "offline"
    assert run.planner_version == "cs-interview-planner-v1"
    assert run.metrics["replay_determinism_ratio"] == 1.0
    metrics = {row.metric: row for row in InterviewEvaluationMetric.select().where(InterviewEvaluationMetric.run_id == run_id)}
    assert "replay_determinism_ratio" in metrics
    assert "hidden_answer_leakage_count" in metrics
    assert metrics["replay_determinism_ratio"].passed is True
    # Threshold rows keep sample count and insufficiency so run history is auditable.
    assert metrics["retrieval_recall_at_5"].sample_count == 6


def test_insufficient_sample_run_is_recorded_as_not_passed(eval_db):
    payload = {
        "retrieval_cases": [],
        "questions": [],
        "judge_cases": [],
        "report_cases": [],
        "candidate_responses": [],
        "agentic_cases": [],
    }
    result = evaluate_fixture(payload)
    assert not result.passed
    run_id = persist_run(result, run_type="offline", created_by="ci")
    run = InterviewEvaluationRun.get_by_id(run_id)
    assert run.passed is False
    assert run.insufficient["replay_determinism_ratio"] is True
    metric = InterviewEvaluationMetric.get(InterviewEvaluationMetric.run_id == run_id, InterviewEvaluationMetric.metric == "replay_determinism_ratio")
    assert metric.insufficient is True
    assert metric.passed is False
