"""Instant first-use binding to the read-only platform interview corpus."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

from peewee import IntegrityError

from api.apps.services.cs_interview.domain import DomainError
from api.apps.services.cs_interview.system_knowledge import (
    SystemKnowledgeConfig,
    load_system_knowledge_config,
)
from api.db.db_models import InterviewKnowledgeBootstrap
from api.db.services.interview_service import InterviewKnowledgeService
from common.misc_utils import get_uuid
from common.time_utils import current_timestamp, datetime_format

LOGGER = logging.getLogger(__name__)
FIELD_TO_PROGRESS_KEY = {
    "interview_experience_dataset_id": "interview_experience",
    "leetcode_dataset_id": "leetcode",
    "fundamentals_dataset_id": "fundamentals",
}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _timestamps() -> dict[str, Any]:
    now = _utcnow()
    stamp = current_timestamp()
    return {
        "create_time": stamp,
        "create_date": datetime_format(now),
        "update_time": stamp,
        "update_date": datetime_format(now),
    }


def _touch() -> dict[str, Any]:
    return {"update_time": current_timestamp(), "update_date": datetime_format(_utcnow())}


def public_bootstrap(row: InterviewKnowledgeBootstrap | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "corpus_version": row.corpus_version,
        "status": row.status,
        "current_stage": row.current_stage,
        "progress": row.progress or {},
        "dataset_ids": row.dataset_ids or {},
        "attempt_count": row.attempt_count,
        "max_attempts": row.max_attempts,
        "error_code": row.error_code,
        "error_message": row.error_message if row.status == "failed" else None,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "created_at": row.create_date,
        "updated_at": row.update_date,
    }


class InterviewKnowledgeBootstrapService:
    @staticmethod
    def latest(tenant_id: str) -> InterviewKnowledgeBootstrap | None:
        return (
            InterviewKnowledgeBootstrap.select()
            .where(InterviewKnowledgeBootstrap.tenant_id == tenant_id)
            .order_by(InterviewKnowledgeBootstrap.create_time.desc())
            .first()
        )

    @staticmethod
    def _create(
        tenant_id: str,
        user_id: str,
        corpus_version: str,
    ) -> tuple[InterviewKnowledgeBootstrap, bool]:
        existing = InterviewKnowledgeBootstrap.get_or_none(
            (InterviewKnowledgeBootstrap.tenant_id == tenant_id)
            & (InterviewKnowledgeBootstrap.corpus_version == corpus_version)
        )
        if existing:
            return existing, True
        try:
            row = InterviewKnowledgeBootstrap.create(
                id=get_uuid(),
                tenant_id=tenant_id,
                user_id=user_id,
                corpus_version=corpus_version,
                status="pending",
                current_stage="queued",
                progress={},
                dataset_ids={},
                max_attempts=max(1, int(os.getenv("CS_INTERVIEW_BOOTSTRAP_MAX_ATTEMPTS", "4"))),
                **_timestamps(),
            )
            return row, False
        except IntegrityError:
            return (
                InterviewKnowledgeBootstrap.get(
                    (InterviewKnowledgeBootstrap.tenant_id == tenant_id)
                    & (InterviewKnowledgeBootstrap.corpus_version == corpus_version)
                ),
                True,
            )

    @classmethod
    def _bind(
        cls,
        row: InterviewKnowledgeBootstrap,
        user_id: str,
        system: SystemKnowledgeConfig,
    ) -> InterviewKnowledgeBootstrap:
        expected_ids = system.dataset_ids
        if row.status == "ready" and dict(row.dataset_ids or {}) == expected_ids:
            return row
        changed = (
            InterviewKnowledgeBootstrap.update(
                status="binding",
                current_stage="binding_system_knowledge",
                user_id=user_id,
                attempt_count=InterviewKnowledgeBootstrap.attempt_count + 1,
                started_at=row.started_at or _utcnow(),
                error_code=None,
                error_message=None,
                **_touch(),
            )
            .where(
                (InterviewKnowledgeBootstrap.id == row.id)
                & (InterviewKnowledgeBootstrap.status != "binding")
            )
            .execute()
        )
        if changed != 1:
            return InterviewKnowledgeBootstrap.get_by_id(row.id)
        try:
            payload: dict[str, Any] = {
                **expected_ids,
                "enabled": True,
                "retrieval_config_snapshot": {
                    "similarity_threshold": 0.2,
                    "vector_similarity_weight": 0.3,
                    "top_n": 5,
                    "top_k": 128,
                    "rerank_id": "",
                },
            }
            existing_config = InterviewKnowledgeService.latest(row.tenant_id, user_id)
            if existing_config:
                payload["id"] = existing_config.id
            knowledge_config = InterviewKnowledgeService.save(row.tenant_id, user_id, payload)
            quality = dict(knowledge_config.metadata_quality_snapshot or {})
            progress = {}
            for field, key in FIELD_TO_PROGRESS_KEY.items():
                summary = quality.get(field) or {}
                total = int(summary.get("document_count") or 0)
                progress[key] = {
                    "total": total,
                    "imported": total,
                    "parsed": total if summary.get("parsed") else 0,
                    "chunks": int(summary.get("chunk_count") or 0),
                }
            InterviewKnowledgeBootstrap.update(
                status="ready",
                current_stage="ready",
                progress=progress,
                dataset_ids=expected_ids,
                completed_at=_utcnow(),
                next_retry_at=None,
                lease_owner=None,
                lease_expires_at=None,
                **_touch(),
            ).where(InterviewKnowledgeBootstrap.id == row.id).execute()
        except Exception as exc:  # noqa: BLE001 - converted into a recoverable onboarding state
            LOGGER.exception("Could not bind platform interview knowledge", extra={"bootstrap_id": row.id})
            InterviewKnowledgeBootstrap.update(
                status="failed",
                current_stage="failed",
                error_code=getattr(exc, "code", "system_knowledge_binding_failed"),
                error_message=str(exc)[:2000],
                completed_at=_utcnow(),
                **_touch(),
            ).where(InterviewKnowledgeBootstrap.id == row.id).execute()
        return InterviewKnowledgeBootstrap.get_by_id(row.id)

    @classmethod
    def ensure(cls, tenant_id: str, user_id: str) -> tuple[InterviewKnowledgeBootstrap, bool]:
        try:
            system = load_system_knowledge_config(required=True)
            row, existed = cls._create(tenant_id, user_id, system.corpus_version)
            return cls._bind(row, user_id, system), existed
        except DomainError as exc:
            row, existed = cls._create(tenant_id, user_id, "unconfigured")
            InterviewKnowledgeBootstrap.update(
                status="failed",
                current_stage="failed",
                error_code=exc.code,
                error_message=exc.message,
                completed_at=_utcnow(),
                **_touch(),
            ).where(InterviewKnowledgeBootstrap.id == row.id).execute()
            return InterviewKnowledgeBootstrap.get_by_id(row.id), existed

    @classmethod
    def retry(cls, tenant_id: str, user_id: str) -> InterviewKnowledgeBootstrap:
        system = load_system_knowledge_config(required=True)
        row, _ = cls._create(tenant_id, user_id, system.corpus_version)
        if row.status == "failed":
            InterviewKnowledgeBootstrap.update(
                status="pending",
                current_stage="queued",
                attempt_count=0,
                error_code=None,
                error_message=None,
                completed_at=None,
                **_touch(),
            ).where(InterviewKnowledgeBootstrap.id == row.id).execute()
            row = InterviewKnowledgeBootstrap.get_by_id(row.id)
        return cls._bind(row, user_id, system)

