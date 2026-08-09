"""Persist offline/live evaluation runs for review and regression tracking.

``persist_run`` stores one ``interview_evaluation_run`` plus one
``interview_evaluation_metric`` per threshold. DB imports are lazy so the
offline CLI still works without a reachable database; persistence is normally
triggered from the ops API or ``--record-run`` when a DB is present.
"""

from __future__ import annotations

import subprocess
from typing import Any

from api.db.db_models import DB
from common.misc_utils import get_uuid


def _git_info() -> dict[str, str | None]:
    try:
        full = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        return {"git_commit": full, "git_short_sha": full[:12]}
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - best effort outside a git checkout
        return {"git_commit": None, "git_short_sha": None}


def persist_run(
    result: Any,
    *,
    run_type: str = "offline",
    fixture_version: str = "",
    prompt_version: str = "",
    planner_version: str = "",
    model_snapshot: dict[str, Any] | None = None,
    knowledge_base_versions: dict[str, Any] | None = None,
    created_by: str | None = None,
) -> str:
    """Persist an EvaluationResult and return the new run id."""
    from api.db.db_models import InterviewEvaluationMetric, InterviewEvaluationRun
    from api.db.services.interview_service import _timestamps

    git = _git_info()
    run_id = get_uuid()
    with DB.atomic():
        InterviewEvaluationRun.create(
            id=run_id,
            run_type=run_type,
            git_commit=git["git_commit"],
            git_short_sha=git["git_short_sha"],
            fixture_version=fixture_version,
            prompt_version=prompt_version,
            planner_version=planner_version,
            model_snapshot=dict(model_snapshot or {}),
            knowledge_base_versions=dict(knowledge_base_versions or {}),
            metrics=result.metrics,
            thresholds=result.thresholds,
            sample_counts=result.sample_counts,
            insufficient=result.insufficient,
            passed=result.passed,
            created_by=created_by,
            **_timestamps(),
        )
        for name, check in result.thresholds.items():
            InterviewEvaluationMetric.create(
                id=get_uuid(),
                run_id=run_id,
                metric=name,
                operator=str(check["operator"]),
                target=float(check["target"]) if check.get("target") is not None else None,
                value=float(check["value"]) if check.get("value") is not None else None,
                passed=bool(check["passed"]),
                sample_count=int(check["sample_count"] or 0),
                insufficient=bool(check["insufficient"]),
                **_timestamps(),
            )
    return run_id
