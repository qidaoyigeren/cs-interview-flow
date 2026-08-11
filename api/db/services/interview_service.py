"""Persistence services for the CS interview vertical application."""

from __future__ import annotations

import logging
import os
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, ClassVar

from peewee import IntegrityError

from api.apps.services.cs_interview.domain import (
    MAX_COMPILER_OUTPUT,
    PLANNER_VERSION,
    PROJECT_CLAIM_MAX_FOLLOWUPS,
    PROMPT_VERSION,
    ROUND_TRANSITIONS,
    SESSION_TRANSITIONS,
    Difficulty,
    DomainError,
    RoundStatus,
    SessionStatus,
    build_initial_interview_plan,
    initial_candidate_state,
    match_resume_to_job,
    metadata_quality,
    question_category_for_round,
    require_transition,
    utcnow,
)
from api.db.db_models import (
    DB,
    CodeSubmission,
    Document,
    InterviewEvent,
    InterviewJob,
    InterviewKnowledgeConfig,
    InterviewModelCall,
    InterviewOperation,
    InterviewOperationCheckpoint,
    InterviewProfile,
    InterviewReport,
    InterviewRequest,
    InterviewResume,
    InterviewRound,
    InterviewSession,
    Knowledgebase,
)
from api.db.services.doc_metadata_service import DocMetadataService
from common.constants import StatusEnum, TaskStatus
from common.misc_utils import get_uuid
from common.time_utils import current_timestamp, datetime_format

ACTIVE_SESSION_STATUSES = {
    SessionStatus.CREATED.value,
    SessionStatus.PREPARING_QUESTION.value,
    SessionStatus.AWAITING_ANSWER.value,
    SessionStatus.EVALUATING.value,
}

LOGGER = logging.getLogger(__name__)

TERMINAL_ROUND_STATUSES = {RoundStatus.COMPLETED.value, RoundStatus.FAILED.value}


def _timestamps() -> dict[str, Any]:
    now = datetime.now(UTC).replace(tzinfo=None)
    timestamp = current_timestamp()
    return {
        "create_time": timestamp,
        "create_date": datetime_format(now),
        "update_time": timestamp,
        "update_date": datetime_format(now),
    }


def _touch() -> dict[str, Any]:
    now = datetime.now(UTC).replace(tzinfo=None)
    return {"update_time": current_timestamp(), "update_date": datetime_format(now)}


def _as_dict(model) -> dict[str, Any]:
    return dict(model.__data__)


def _public_json(value: Any) -> Any:
    """Normalize DTO values exactly once before storage or API serialization."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, dict):
        return {key: _public_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public_json(item) for item in value]
    return value


def _scope(model, resource_id: str, tenant_id: str, user_id: str):
    row = model.get_or_none((model.id == resource_id) & (model.tenant_id == tenant_id) & (model.user_id == user_id))
    if row is None:
        raise DomainError("not_found", "Resource not found.", http_status=404)
    return row


def validate_profile_payload(payload: dict[str, Any], *, partial: bool = False, tenant_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
    from api.apps.services.cs_interview.domain import ROLE_CAPABILITY_TREES

    allowed = {
        "name",
        "target_role",
        "target_level",
        "technology_stack",
        "focus_topics",
        "excluded_topics",
        "initial_difficulty",
        "preferred_categories",
        "question_count",
        "max_followups",
        "resume_id",
        "job_id",
    }
    result = {key: value for key, value in payload.items() if key in allowed}
    required = {"name", "target_role", "target_level", "resume_id", "job_id"}
    if not partial and required - set(result):
        raise DomainError("invalid_profile", f"Missing profile fields: {', '.join(sorted(required - set(result)))}.")
    if "target_role" in result and result["target_role"] not in ROLE_CAPABILITY_TREES:
        raise DomainError("invalid_profile", "Unsupported target role.")
    if "target_level" in result and result["target_level"] not in {"junior", "mid", "senior", "staff"}:
        raise DomainError("invalid_profile", "Unsupported target level.")
    if "initial_difficulty" in result and result["initial_difficulty"] not in {item.value for item in Difficulty}:
        raise DomainError("invalid_profile", "Unsupported initial difficulty.")
    for key in ("technology_stack", "focus_topics", "excluded_topics", "preferred_categories"):
        if key in result and not isinstance(result[key], list):
            raise DomainError("invalid_profile", f"{key} must be a list.")
        if key in result:
            result[key] = list(dict.fromkeys(str(item).strip() for item in result[key] if str(item).strip()))
            if len(result[key]) > 50 or any(len(item) > 128 for item in result[key]):
                raise DomainError("invalid_profile", f"{key} contains too many or overly long values.")
    if "preferred_categories" in result and not set(result["preferred_categories"]) <= {
        "interview_experience",
        "leetcode",
        "baguwen",
    }:
        raise DomainError("invalid_profile", "Unsupported preferred category.")
    if set(result.get("focus_topics", [])) & set(result.get("excluded_topics", [])):
        raise DomainError("invalid_profile", "A topic cannot be both focused and excluded.")
    if "question_count" in result:
        result["question_count"] = int(result["question_count"])
        if not 1 <= result["question_count"] <= 20:
            raise DomainError("invalid_profile", "question_count must be between 1 and 20.")
    if "max_followups" in result:
        result["max_followups"] = int(result["max_followups"])
        if not 0 <= result["max_followups"] <= 5:
            raise DomainError("invalid_profile", "max_followups must be between 0 and 5.")
    for key in ("name", "target_level"):
        if key in result:
            result[key] = str(result[key]).strip()
            if not result[key]:
                raise DomainError("invalid_profile", f"{key} cannot be empty.")
    if len(result.get("name", "")) > 128:
        raise DomainError("invalid_profile", "name cannot exceed 128 characters.")
    if "resume_id" in result:
        resume_id = str(result["resume_id"] or "").strip()
        if not resume_id:
            result["resume_id"] = None
        elif tenant_id and user_id:
            resume = InterviewResume.get_or_none((InterviewResume.id == resume_id) & (InterviewResume.tenant_id == tenant_id) & (InterviewResume.user_id == user_id))
            if resume is None or not resume.extraction:
                raise DomainError("invalid_profile", "The referenced resume must exist and be extracted.")
    if "job_id" in result:
        job_id = str(result["job_id"] or "").strip()
        if not job_id:
            result["job_id"] = None
        elif tenant_id and user_id:
            job = InterviewJob.get_or_none((InterviewJob.id == job_id) & (InterviewJob.tenant_id == tenant_id) & (InterviewJob.user_id == user_id))
            if job is None or not job.extraction:
                raise DomainError("invalid_profile", "The referenced job must exist and be extracted.")
    if not partial and (not result.get("resume_id") or not result.get("job_id")):
        raise DomainError("invalid_profile", "A profile must reference both an extracted resume and an extracted job.")
    return result


class InterviewProfileService:
    @staticmethod
    def create(tenant_id: str, user_id: str, payload: dict[str, Any]) -> InterviewProfile:
        data = validate_profile_payload(payload, tenant_id=tenant_id, user_id=user_id)
        data.setdefault("technology_stack", [])
        data.setdefault("focus_topics", [])
        data.setdefault("excluded_topics", [])
        data.setdefault("preferred_categories", [])
        data.setdefault("initial_difficulty", Difficulty.MEDIUM.value)
        data.setdefault("question_count", 8)
        data.setdefault("max_followups", 2)
        return InterviewProfile.create(id=get_uuid(), tenant_id=tenant_id, user_id=user_id, **data, **_timestamps())

    @staticmethod
    def update(profile_id: str, tenant_id: str, user_id: str, payload: dict[str, Any]) -> InterviewProfile:
        profile = _scope(InterviewProfile, profile_id, tenant_id, user_id)
        data = validate_profile_payload(payload, partial=True, tenant_id=tenant_id, user_id=user_id)
        if not data:
            return profile
        current = {
            "name": profile.name,
            "target_role": profile.target_role,
            "target_level": profile.target_level,
            "technology_stack": profile.technology_stack,
            "focus_topics": profile.focus_topics,
            "excluded_topics": profile.excluded_topics,
            "initial_difficulty": profile.initial_difficulty,
            "preferred_categories": profile.preferred_categories,
            "question_count": profile.question_count,
            "max_followups": profile.max_followups,
            "resume_id": profile.resume_id,
            "job_id": profile.job_id,
        }
        values = validate_profile_payload({**current, **data})
        InterviewProfile.update(**values, **_touch()).where((InterviewProfile.id == profile.id) & (InterviewProfile.tenant_id == tenant_id) & (InterviewProfile.user_id == user_id)).execute()
        return _scope(InterviewProfile, profile.id, tenant_id, user_id)

    @staticmethod
    def get(profile_id: str, tenant_id: str, user_id: str) -> InterviewProfile:
        return _scope(InterviewProfile, profile_id, tenant_id, user_id)

    @staticmethod
    def list(tenant_id: str, user_id: str) -> list[InterviewProfile]:
        return list(InterviewProfile.select().where((InterviewProfile.tenant_id == tenant_id) & (InterviewProfile.user_id == user_id)).order_by(InterviewProfile.update_time.desc()))

    @staticmethod
    def delete(profile_id: str, tenant_id: str, user_id: str) -> None:
        profile = _scope(InterviewProfile, profile_id, tenant_id, user_id)
        if InterviewSession.select().where((InterviewSession.profile_id == profile.id) & (InterviewSession.tenant_id == tenant_id) & (InterviewSession.user_id == user_id)).exists():
            raise DomainError("profile_in_use", "Profiles referenced by interview history cannot be deleted.", http_status=409)
        InterviewProfile.delete().where((InterviewProfile.id == profile.id) & (InterviewProfile.tenant_id == tenant_id) & (InterviewProfile.user_id == user_id)).execute()


class InterviewResumeService:
    @staticmethod
    def get(resume_id: str, tenant_id: str, user_id: str) -> InterviewResume:
        return _scope(InterviewResume, resume_id, tenant_id, user_id)

    @staticmethod
    def list(tenant_id: str, user_id: str) -> list[InterviewResume]:
        return list(InterviewResume.select().where((InterviewResume.tenant_id == tenant_id) & (InterviewResume.user_id == user_id)).order_by(InterviewResume.update_time.desc()))

    @staticmethod
    def sync_parse(resume: InterviewResume) -> InterviewResume:
        from api.apps.services.cs_interview.resume_service import parse_status

        status = parse_status(resume)
        if status != resume.parse_status:
            InterviewResume.update(parse_status=status, **_touch()).where(
                (InterviewResume.id == resume.id) & (InterviewResume.tenant_id == resume.tenant_id) & (InterviewResume.user_id == resume.user_id)
            ).execute()
            resume = _scope(InterviewResume, resume.id, resume.tenant_id, resume.user_id)
        return resume


class InterviewJobService:
    @staticmethod
    def get(job_id: str, tenant_id: str, user_id: str) -> InterviewJob:
        return _scope(InterviewJob, job_id, tenant_id, user_id)

    @staticmethod
    def list(tenant_id: str, user_id: str) -> list[InterviewJob]:
        return list(InterviewJob.select().where((InterviewJob.tenant_id == tenant_id) & (InterviewJob.user_id == user_id)).order_by(InterviewJob.update_time.desc()))

    @staticmethod
    def replace_extraction(job_id: str, tenant_id: str, user_id: str, extraction: dict[str, Any]) -> InterviewJob:
        from api.apps.services.cs_interview.domain import JOB_EXTRACTION_VERSION, validate_job_extraction

        job = _scope(InterviewJob, job_id, tenant_id, user_id)
        validated = validate_job_extraction(extraction, job.source_text)
        InterviewJob.update(
            extraction=validated,
            extraction_version=JOB_EXTRACTION_VERSION,
            extracted_at=utcnow(),
            **_touch(),
        ).where((InterviewJob.id == job.id) & (InterviewJob.tenant_id == tenant_id) & (InterviewJob.user_id == user_id)).execute()
        return _scope(InterviewJob, job.id, tenant_id, user_id)

    @staticmethod
    def delete(job_id: str, tenant_id: str, user_id: str) -> None:
        job = _scope(InterviewJob, job_id, tenant_id, user_id)
        # Sessions own immutable snapshots, so source erasure does not rewrite
        # interview history. Profiles are detached and cannot start a new run.
        InterviewProfile.update(job_id=None, **_touch()).where((InterviewProfile.job_id == job.id) & (InterviewProfile.tenant_id == tenant_id) & (InterviewProfile.user_id == user_id)).execute()
        InterviewJob.delete().where((InterviewJob.id == job.id) & (InterviewJob.tenant_id == tenant_id) & (InterviewJob.user_id == user_id)).execute()


def _dataset_documents(dataset_id: str) -> list[Document]:
    return list(Document.select().where((Document.kb_id == dataset_id) & (Document.status == StatusEnum.VALID.value)))


def inspect_dataset(dataset_id: str, tenant_id: str, expected_content_type: str) -> dict[str, Any]:
    kb = Knowledgebase.get_or_none((Knowledgebase.id == dataset_id) & (Knowledgebase.tenant_id == tenant_id) & (Knowledgebase.status == StatusEnum.VALID.value))
    if kb is None:
        raise DomainError("dataset_not_found", "Dataset does not exist in the current tenant.", http_status=404)
    docs = _dataset_documents(dataset_id)
    parsing_issues = []
    for doc in docs:
        if doc.run in {TaskStatus.RUNNING.value, TaskStatus.CANCEL.value, TaskStatus.FAIL.value}:
            parsing_issues.append({"document_id": doc.id, "name": doc.name, "status": doc.run})
        elif doc.run == TaskStatus.UNSTART.value and doc.chunk_num == 0:
            parsing_issues.append({"document_id": doc.id, "name": doc.name, "status": "unparsed"})
    metadata_rows: list[dict[str, Any]] = []
    metadata_error = None
    if docs:
        try:
            metadata_map = DocMetadataService.get_metadata_for_documents([doc.id for doc in docs], dataset_id)
            metadata_rows = [dict(metadata_map.get(doc.id, {})) for doc in docs]
        except Exception as exc:  # noqa: BLE001 - metadata backends raise connector-specific errors
            metadata_error = type(exc).__name__
    quality = metadata_quality(metadata_rows, expected_content_type)
    if metadata_error:
        quality["metadata_read_error"] = metadata_error
        quality["ready"] = False
    return {
        "id": kb.id,
        "name": kb.name,
        "tenant_id": kb.tenant_id,
        "document_count": len(docs),
        "chunk_count": kb.chunk_num,
        "parsed": bool(docs) and not parsing_issues,
        "parsing_issues": parsing_issues[:20],
        "metadata_quality": quality,
        "updated_at": kb.update_date,
        "version": str(kb.update_time or kb.create_time or ""),
        "embedding_model": kb.embd_id,
        "anchor_group_ids": sorted(
            {
                str(metadata.get("anchor_group_id"))
                for metadata in metadata_rows
                if str(metadata.get("anchor_group_id") or "").strip()
            }
        ),
    }


class InterviewKnowledgeService:
    FIELDS: ClassVar[dict[str, str]] = {
        "interview_experience_dataset_id": "interview_experience",
        "leetcode_dataset_id": "leetcode",
        "fundamentals_dataset_id": "fundamentals",
    }

    @classmethod
    def _system_quality_snapshot(cls, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Return the platform owner's validated snapshot for an exact system binding."""
        from api.apps.services.cs_interview.system_knowledge import load_system_knowledge_config

        system = load_system_knowledge_config()
        if system is None or tenant_id == system.tenant_id:
            return None
        if any(str(payload.get(field, "")) != dataset_id for field, dataset_id in system.dataset_ids.items()):
            return None

        source = (
            InterviewKnowledgeConfig.select()
            .where(
                (InterviewKnowledgeConfig.tenant_id == system.tenant_id)
                & InterviewKnowledgeConfig.enabled
                & (InterviewKnowledgeConfig.interview_experience_dataset_id == system.dataset_ids["interview_experience_dataset_id"])
                & (InterviewKnowledgeConfig.leetcode_dataset_id == system.dataset_ids["leetcode_dataset_id"])
                & (InterviewKnowledgeConfig.fundamentals_dataset_id == system.dataset_ids["fundamentals_dataset_id"])
            )
            .order_by(InterviewKnowledgeConfig.update_time.desc())
            .first()
        )
        if source is None:
            raise DomainError(
                "system_knowledge_unvalidated",
                "The platform interview knowledge bases do not have a validated release snapshot.",
                http_status=503,
            )

        quality = deepcopy(source.metadata_quality_snapshot or {})
        datasets = {
            row.id: row
            for row in Knowledgebase.select().where(
                (Knowledgebase.tenant_id == system.tenant_id)
                & (Knowledgebase.status == StatusEnum.VALID.value)
                & Knowledgebase.id.in_(tuple(system.dataset_ids.values()))
            )
        }
        from api.apps.services.cs_interview.competencies import ANCHOR_GROUPS

        available_anchor_groups: set[str] = set()
        for field, dataset_id in system.dataset_ids.items():
            summary = quality.get(field)
            dataset = datasets.get(dataset_id)
            current_version = str(dataset.update_time or dataset.create_time or "") if dataset else ""
            if (
                not isinstance(summary, dict)
                or str(summary.get("id", "")) != dataset_id
                or str(summary.get("tenant_id", "")) != system.tenant_id
                or not summary.get("parsed")
                or not (summary.get("metadata_quality") or {}).get("ready")
                or str(summary.get("version", "")) != current_version
            ):
                raise DomainError(
                    "system_knowledge_snapshot_stale",
                    "The platform interview knowledge release must be revalidated before it can be bound.",
                    http_status=503,
                )
            summary["read_only"] = True
            available_anchor_groups.update(str(value) for value in summary.get("anchor_group_ids", []))
        if not set(ANCHOR_GROUPS).issubset(available_anchor_groups):
            raise DomainError(
                "system_knowledge_snapshot_stale",
                "The platform interview knowledge release is missing reviewed capability anchors.",
                http_status=503,
            )
        return quality

    @classmethod
    def validate_bindings(cls, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from api.apps.services.cs_interview.system_knowledge import load_system_knowledge_config

        missing = set(cls.FIELDS) - set(payload)
        if missing:
            raise DomainError("invalid_knowledge_config", f"Missing dataset bindings: {', '.join(sorted(missing))}.")
        ids = [str(payload[field]) for field in cls.FIELDS]
        if len(set(ids)) != 3:
            raise DomainError("datasets_not_independent", "The three interview datasets must be different.")
        system_config = load_system_knowledge_config()
        quality = {}
        for field, content_type in cls.FIELDS.items():
            dataset_id = str(payload[field])
            owner_tenant_id = (
                system_config.owner_for(field, dataset_id, tenant_id)
                if system_config
                else tenant_id
            )
            summary = inspect_dataset(dataset_id, owner_tenant_id, content_type)
            summary["read_only"] = owner_tenant_id != tenant_id
            quality[field] = summary
            if not summary["parsed"]:
                raise DomainError("dataset_not_parsed", f"Dataset {summary['name']} has unparsed or failed documents.", http_status=409)
        from api.apps.services.cs_interview.competencies import ANCHOR_GROUPS

        available_anchor_groups = {
            str(anchor_group_id)
            for summary in quality.values()
            for anchor_group_id in summary.get("anchor_group_ids", [])
        }
        missing_anchor_groups = sorted(set(ANCHOR_GROUPS) - available_anchor_groups)
        if missing_anchor_groups:
            raise DomainError(
                "anchor_dataset_incomplete",
                "Knowledge datasets are missing reviewed anchor groups: " + ", ".join(missing_anchor_groups),
                http_status=409,
            )
        return quality

    @classmethod
    def save(cls, tenant_id: str, user_id: str, payload: dict[str, Any]) -> InterviewKnowledgeConfig:
        quality = cls._system_quality_snapshot(tenant_id, payload) or cls.validate_bindings(tenant_id, payload)
        retrieval = payload.get("retrieval_config_snapshot") or {}
        try:
            retrieval = {
                "similarity_threshold": max(0.0, min(float(retrieval.get("similarity_threshold", 0.2)), 1.0)),
                "vector_similarity_weight": max(0.0, min(float(retrieval.get("vector_similarity_weight", 0.3)), 1.0)),
                "top_n": max(1, min(int(retrieval.get("top_n", 5)), 20)),
                "top_k": max(1, min(int(retrieval.get("top_k", 1024)), 2048)),
                "rerank_id": str(retrieval.get("rerank_id", "")),
                "embedding_models": {field: summary["embedding_model"] for field, summary in quality.items()},
                "dataset_tenant_ids": {
                    summary["id"]: summary["tenant_id"] for summary in quality.values()
                },
            }
        except (TypeError, ValueError) as exc:
            raise DomainError("invalid_knowledge_config", "Retrieval configuration contains invalid numbers.") from exc
        values = {field: str(payload[field]) for field in cls.FIELDS}
        config_id = payload.get("id")
        with DB.atomic():
            if config_id:
                config = _scope(InterviewKnowledgeConfig, str(config_id), tenant_id, user_id)
                InterviewKnowledgeConfig.update(
                    **values,
                    retrieval_config_snapshot=retrieval,
                    metadata_quality_snapshot=quality,
                    enabled=bool(payload.get("enabled", True)),
                    **_touch(),
                ).where(InterviewKnowledgeConfig.id == config.id).execute()
                return InterviewKnowledgeConfig.get_by_id(config.id)
            return InterviewKnowledgeConfig.create(
                id=get_uuid(),
                tenant_id=tenant_id,
                user_id=user_id,
                **values,
                retrieval_config_snapshot=retrieval,
                metadata_quality_snapshot=quality,
                enabled=bool(payload.get("enabled", True)),
                **_timestamps(),
            )

    @staticmethod
    def get(config_id: str, tenant_id: str, user_id: str) -> InterviewKnowledgeConfig:
        return _scope(InterviewKnowledgeConfig, config_id, tenant_id, user_id)

    @staticmethod
    def latest(tenant_id: str, user_id: str) -> InterviewKnowledgeConfig | None:
        return (
            InterviewKnowledgeConfig.select()
            .where(
                (InterviewKnowledgeConfig.tenant_id == tenant_id)
                & (InterviewKnowledgeConfig.user_id == user_id)
                & InterviewKnowledgeConfig.enabled
            )
            .order_by(InterviewKnowledgeConfig.update_time.desc())
            .first()
        )

    @classmethod
    def revalidate(cls, config: InterviewKnowledgeConfig) -> dict[str, Any]:
        payload = {field: getattr(config, field) for field in cls.FIELDS}
        quality = cls._system_quality_snapshot(config.tenant_id, payload) or cls.validate_bindings(config.tenant_id, payload)
        InterviewKnowledgeConfig.update(metadata_quality_snapshot=quality, **_touch()).where(InterviewKnowledgeConfig.id == config.id).execute()
        return quality

    @staticmethod
    def list_available(tenant_id: str) -> list[dict[str, Any]]:
        from api.apps.services.cs_interview.system_knowledge import load_system_knowledge_config

        system_config = load_system_knowledge_config()
        allowed_ids = set(system_config.dataset_ids.values()) if system_config else set()
        scope = Knowledgebase.tenant_id == tenant_id
        if allowed_ids:
            scope = scope | Knowledgebase.id.in_(allowed_ids)
        rows = (
            Knowledgebase.select()
            .where(
                (Knowledgebase.status == StatusEnum.VALID.value)
                & scope
            )
            .order_by(Knowledgebase.update_time.desc())
        )
        return [
            {
                "id": row.id,
                "name": row.name,
                "document_count": row.doc_num,
                "chunk_count": row.chunk_num,
                "embedding_model": row.embd_id,
                "read_only": row.tenant_id != tenant_id,
                "updated_at": row.update_date,
            }
            for row in rows
        ]


class InterviewSessionRepository:
    @staticmethod
    def create(tenant_id: str, user_id: str, profile_id: str, knowledge_config_id: str) -> InterviewSession:
        profile = InterviewProfileService.get(profile_id, tenant_id, user_id)
        config = InterviewKnowledgeService.get(knowledge_config_id, tenant_id, user_id)
        if not config.enabled:
            raise DomainError("knowledge_config_disabled", "The knowledge configuration is disabled.", http_status=409)
        limit = max(1, int(os.getenv("CS_INTERVIEW_MAX_ACTIVE_SESSIONS", "2")))
        active_count = (
            InterviewSession.select().where((InterviewSession.tenant_id == tenant_id) & (InterviewSession.user_id == user_id) & (InterviewSession.status.in_(ACTIVE_SESSION_STATUSES))).count()
        )
        if active_count >= limit:
            raise DomainError("session_limit", "The active interview session limit has been reached.", http_status=409)
        quality = InterviewKnowledgeService.revalidate(config)
        versions = {
            field: {
                "dataset_id": getattr(config, field),
                "version": summary["version"],
                "document_count": summary["document_count"],
            }
            for field, summary in quality.items()
        }
        resume_row = InterviewResume.get_or_none((InterviewResume.id == profile.resume_id) & (InterviewResume.tenant_id == tenant_id) & (InterviewResume.user_id == user_id))
        if resume_row is None or not resume_row.extraction:
            raise DomainError("resume_not_extracted", "The profile resume must be extracted before starting an interview.", http_status=409)
        from api.apps.services.cs_interview.resume_service import resume_needs_extraction

        if resume_needs_extraction(resume_row):
            raise DomainError(
                "resume_outdated_extraction",
                "The resume extraction is outdated; re-extract the resume before starting an interview.",
                http_status=409,
            )
        job_row = InterviewJob.get_or_none((InterviewJob.id == profile.job_id) & (InterviewJob.tenant_id == tenant_id) & (InterviewJob.user_id == user_id))
        if job_row is None or not job_row.extraction:
            raise DomainError("job_not_extracted", "The profile job must be extracted before starting an interview.", http_status=409)
        profile_snapshot = {
            key: deepcopy(value)
            for key, value in _as_dict(profile).items()
            if key
            in {
                "id",
                "name",
                "target_role",
                "target_level",
                "technology_stack",
                "focus_topics",
                "excluded_topics",
                "initial_difficulty",
                "preferred_categories",
                "question_count",
                "max_followups",
                "resume_id",
                "job_id",
            }
        }
        resume_snapshot = deepcopy(resume_row.extraction)
        job_snapshot = {
            "id": job_row.id,
            "name": job_row.name,
            "source_type": job_row.source_type,
            "source_text": job_row.source_text,
            "extraction": deepcopy(job_row.extraction),
            "extraction_version": job_row.extraction_version,
            "extracted_at": job_row.extracted_at.isoformat() if job_row.extracted_at else None,
        }
        match_snapshot = match_resume_to_job(resume_snapshot, job_snapshot["extraction"])
        initial_plan = build_initial_interview_plan(job_snapshot["extraction"], match_snapshot, profile_snapshot)
        # Freeze the project attack map once from the resume/JD snapshots.  It is
        # seeded into candidate_state and never regenerated mid-session; only
        # statuses/attempts mutate (see CandidateState.project_claim_state).
        from api.apps.services.cs_interview.domain import build_project_attack_map

        attack_map = build_project_attack_map(resume_snapshot, job_snapshot["extraction"], profile_snapshot)
        candidate_state = initial_candidate_state(attack_map)
        # Freeze the competency/rubric/anchor snapshot once at creation. The
        # running session must never re-read the mutable competency catalog.
        from api.apps.services.cs_interview.competencies import RUBRIC_VERSION, normalize_competency_snapshot

        competency_snapshot = normalize_competency_snapshot(str(profile_snapshot.get("target_role") or "cs_general"), str(profile_snapshot.get("target_level") or "all"))
        knowledge_config_snapshot = {
            "id": config.id,
            "interview_experience_dataset_id": config.interview_experience_dataset_id,
            "leetcode_dataset_id": config.leetcode_dataset_id,
            "fundamentals_dataset_id": config.fundamentals_dataset_id,
            "retrieval_config_snapshot": deepcopy(config.retrieval_config_snapshot),
            "metadata_quality_snapshot": deepcopy(quality),
        }
        session_id = get_uuid()
        # Resolve a stable experiment variant once, before the session exists.
        # The variant (and its assignment row) is frozen at creation: a session
        # never switches variants mid-flight.
        planner_version = PLANNER_VERSION
        prompt_version = PROMPT_VERSION
        model_config_snapshot: dict[str, Any] = {}
        variant: dict[str, Any] | None = None
        from api.apps.services.cs_interview.experiment_service import resolve_variant

        variant = resolve_variant(tenant_id, user_id, session_id)
        if variant:
            planner_version = str(variant.get("planner_version") or PLANNER_VERSION)
            prompt_version = str(variant.get("prompt_version") or PROMPT_VERSION)
            retrieval_override = variant.get("retrieval_config")
            if isinstance(retrieval_override, dict):
                knowledge_config_snapshot["retrieval_config_snapshot"] = {
                    **(knowledge_config_snapshot.get("retrieval_config_snapshot") or {}),
                    **retrieval_override,
                }
            model_config_snapshot["experiment_variant"] = deepcopy(variant)
        session = InterviewSession.create(
            id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            profile_id=profile.id,
            knowledge_config_id=config.id,
            status=SessionStatus.CREATED.value,
            current_difficulty=profile.initial_difficulty,
            max_questions=profile.question_count,
            max_followups=profile.max_followups,
            completed_question_count=0,
            current_round_sequence=0,
            state_version=0,
            model_config_snapshot=model_config_snapshot,
            knowledge_base_versions=versions,
            profile_snapshot=profile_snapshot,
            knowledge_config_snapshot=knowledge_config_snapshot,
            job_snapshot=job_snapshot,
            resume_snapshot=resume_snapshot,
            match_snapshot=match_snapshot,
            initial_interview_plan=deepcopy(initial_plan),
            initial_candidate_state=deepcopy(candidate_state),
            current_interview_plan=deepcopy(initial_plan),
            current_candidate_state=deepcopy(candidate_state),
            competency_snapshot=deepcopy(competency_snapshot),
            rubric_version=str((competency_snapshot or {}).get("rubric_version") or RUBRIC_VERSION),
            planner_version=planner_version,
            prompt_version=prompt_version,
            performance_snapshot={},
            **_timestamps(),
        )
        if variant:
            from api.apps.services.cs_interview.experiment_service import assign

            assign(tenant_id, user_id, session_id, variant)
        return session

    @staticmethod
    def get(session_id: str, tenant_id: str, user_id: str) -> InterviewSession:
        return _scope(InterviewSession, session_id, tenant_id, user_id)

    @staticmethod
    def list(tenant_id: str, user_id: str, *, page: int = 1, page_size: int = 20) -> list[InterviewSession]:
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        return list(
            InterviewSession.select()
            .where((InterviewSession.tenant_id == tenant_id) & (InterviewSession.user_id == user_id))
            .order_by(InterviewSession.update_time.desc())
            .paginate(page, page_size)
        )

    @staticmethod
    def rounds(session_id: str) -> list[InterviewRound]:
        return list(InterviewRound.select().where(InterviewRound.session_id == session_id).order_by(InterviewRound.sequence.asc()))

    @staticmethod
    def active_round(session_id: str) -> InterviewRound | None:
        return InterviewRound.get_or_none((InterviewRound.session_id == session_id) & (InterviewRound.active_guard == "active"))

    @staticmethod
    def transition(session: InterviewSession, target: str, *, expected_version: int | None = None, **updates) -> InterviewSession:
        require_transition(session.status, target, SESSION_TRANSITIONS)
        if expected_version is not None and session.state_version != expected_version:
            raise DomainError("state_conflict", "The session changed; refresh it before retrying.", http_status=409)
        values = {"status": target, "state_version": session.state_version + 1, **updates, **_touch()}
        query = InterviewSession.update(**values).where(
            (InterviewSession.id == session.id)
            & (InterviewSession.tenant_id == session.tenant_id)
            & (InterviewSession.user_id == session.user_id)
            & (InterviewSession.state_version == session.state_version)
        )
        if query.execute() != 1:
            raise DomainError("state_conflict", "Another request already changed this session.", http_status=409)
        LOGGER.info(
            "CS interview session transition",
            extra={
                "session_id": session.id,
                "from_status": session.status,
                "to_status": target,
                "state_version": session.state_version + 1,
            },
        )
        return InterviewSessionRepository.get(session.id, session.tenant_id, session.user_id)

    @staticmethod
    def transition_round(round_: InterviewRound, target: str, **updates) -> InterviewRound:
        require_transition(round_.status, target, ROUND_TRANSITIONS)
        if target in TERMINAL_ROUND_STATUSES:
            updates["active_guard"] = None
        changed = InterviewRound.update(status=target, **updates, **_touch()).where((InterviewRound.id == round_.id) & (InterviewRound.status == round_.status)).execute()
        if changed != 1:
            raise DomainError("state_conflict", "Another request already changed this interview round.", http_status=409)
        LOGGER.info(
            "CS interview round transition",
            extra={"session_id": round_.session_id, "round_id": round_.id, "from_status": round_.status, "to_status": target},
        )
        return InterviewRound.get_by_id(round_.id)

    @staticmethod
    def create_round(session: InterviewSession, snapshot: dict[str, Any]) -> InterviewRound:
        if InterviewSessionRepository.active_round(session.id):
            raise DomainError("active_round_exists", "The session already has an active round.", http_status=409)
        try:
            return InterviewRound.create(
                id=get_uuid(),
                session_id=session.id,
                sequence=session.current_round_sequence + 1,
                status=RoundStatus.PREPARING.value,
                active_guard="active",
                question_id=snapshot["question_id"],
                category=snapshot["category"],
                topic=snapshot["topic"],
                question_type=snapshot["question_type"],
                difficulty=snapshot["difficulty"],
                question_text=snapshot["question_text"],
                reference_answer=snapshot["reference_answer"],
                evaluation_rubric=snapshot["evaluation_rubric"],
                retrieval_query=snapshot["retrieval_query"],
                retrieval_evidence=snapshot["retrieval_evidence"],
                resume_probe=snapshot.get("resume_probe"),
                evidence_versions=snapshot["evidence_versions"],
                source_version=snapshot["source_version"],
                prompt_version=snapshot["prompt_version"],
                model_version=snapshot["model_version"],
                target_requirement_id=snapshot.get("target_requirement_id"),
                target_requirement=snapshot.get("target_requirement"),
                question_kind=snapshot.get("question_kind") or "adaptive",
                competency_id=snapshot.get("competency_id") or str(snapshot.get("topic") or ""),
                anchor_group_id=snapshot.get("anchor_group_id") or "",
                expected_evidence=snapshot.get("expected_evidence") or {},
                rubric_version=snapshot.get("rubric_version") or "",
                selected_action=snapshot["planner_action"]["selected_action"],
                selection_reason=snapshot["planner_action"]["reason"],
                planner_actions=[snapshot["planner_action"]],
                answer_state={},
                evidence_evaluation={},
                question_validation=snapshot["question_validation"],
                candidate_answers=[],
                followup_questions=[],
                followup_count=0,
                asked_at=utcnow(),
                **_timestamps(),
            )
        except IntegrityError as exc:
            raise DomainError("active_round_exists", "The session already has an active round.", http_status=409) from exc

    @staticmethod
    def abort(session: InterviewSession, *, expected_version: int | None = None) -> InterviewSession:
        with DB.atomic():
            session = InterviewSessionRepository.get(session.id, session.tenant_id, session.user_id)
            if session.status in {SessionStatus.COMPLETED.value, SessionStatus.ABORTED.value}:
                raise DomainError("session_terminal", "A completed or aborted interview cannot be changed.", http_status=409)
            active = InterviewSessionRepository.active_round(session.id)
            if active:
                InterviewRound.update(status=RoundStatus.FAILED.value, active_guard=None, **_touch()).where(InterviewRound.id == active.id).execute()
            return InterviewSessionRepository.transition(session, SessionStatus.ABORTED.value, expected_version=expected_version, aborted_at=utcnow())

    @staticmethod
    def anonymize(session_id: str, tenant_id: str, user_id: str) -> InterviewSession:
        """Erase candidate/JD content while retaining non-personal score totals."""

        session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
        with DB.atomic():
            if session.status in ACTIVE_SESSION_STATUSES:
                session = InterviewSessionRepository.abort(session)
            operation_ids = [
                row.id
                for row in InterviewOperation.select(InterviewOperation.id).where(
                    (InterviewOperation.session_id == session.id)
                    & (InterviewOperation.tenant_id == tenant_id)
                    & (InterviewOperation.user_id == user_id)
                )
            ]
            InterviewRound.update(
                candidate_answers=[],
                resume_probe=None,
                target_requirement_id=None,
                target_requirement=None,
                selection_reason="",
                planner_actions=[],
                answer_state={},
                **_touch(),
            ).where(InterviewRound.session_id == session.id).execute()
            CodeSubmission.delete().where(
                (CodeSubmission.session_id == session.id)
                & (CodeSubmission.tenant_id == tenant_id)
                & (CodeSubmission.user_id == user_id)
            ).execute()
            InterviewReport.update(
                jd_verification_matrix=[],
                skill_verification=None,
                report_markdown="[personal data deleted]",
                **_touch(),
            ).where(InterviewReport.session_id == session.id).execute()
            InterviewSession.update(
                profile_snapshot={"redacted": True},
                resume_snapshot={"redacted": True},
                job_snapshot={"redacted": True},
                match_snapshot=[],
                initial_interview_plan=[],
                current_interview_plan=[],
                current_candidate_state={"redacted": True},
                **_touch(),
            ).where(
                (InterviewSession.id == session.id)
                & (InterviewSession.tenant_id == tenant_id)
                & (InterviewSession.user_id == user_id)
            ).execute()
            if operation_ids:
                InterviewEvent.delete().where(InterviewEvent.operation_id.in_(operation_ids)).execute()
                InterviewOperationCheckpoint.delete().where(
                    InterviewOperationCheckpoint.operation_id.in_(operation_ids)
                ).execute()
                InterviewModelCall.update(prompt_snapshot={"redacted": True}, **_touch()).where(
                    InterviewModelCall.operation_id.in_(operation_ids)
                ).execute()
                InterviewOperation.update(
                    payload={},
                    checkpoint={"redacted": True},
                    result_summary={"redacted": True},
                    **_touch(),
                ).where(InterviewOperation.id.in_(operation_ids)).execute()
                InterviewRequest.update(response={"redacted": True}, **_touch()).where(
                    InterviewRequest.operation_id.in_(operation_ids)
                ).execute()
        return InterviewSessionRepository.get(session.id, tenant_id, user_id)


class InterviewRequestService:
    @staticmethod
    def begin(session_id: str, request_id: str, operation: str, digest: str, *, operation_id: str | None = None) -> tuple[InterviewRequest, bool]:
        if not request_id or len(request_id) > 128:
            raise DomainError("invalid_request_id", "request_id is required and must be at most 128 characters.")
        existing = InterviewRequest.get_or_none((InterviewRequest.session_id == session_id) & (InterviewRequest.request_id == request_id))
        if existing:
            if existing.payload_hash != digest or existing.operation != operation:
                raise DomainError("idempotency_conflict", "request_id was already used with another payload.", http_status=409)
            if operation_id and existing.operation_id != operation_id:
                raise DomainError("idempotency_conflict", "request_id belongs to another operation.", http_status=409)
            if existing.status == "queued" and operation_id:
                InterviewRequest.update(status="processing", **_touch()).where(InterviewRequest.id == existing.id).execute()
                return InterviewRequest.get_by_id(existing.id), False
            if existing.status == "processing":
                if operation_id:
                    return existing, False
                return existing, True
            if existing.status == "failed":
                saved = existing.response.get("error", {})
                raise DomainError(
                    str(saved.get("code", "request_failed")),
                    str(saved.get("message", "The previous request failed.")),
                    http_status=int(saved.get("http_status", 409)),
                )
            return existing, True
        try:
            return (
                InterviewRequest.create(
                    id=get_uuid(),
                    session_id=session_id,
                    request_id=request_id,
                    operation=operation,
                    payload_hash=digest,
                    status="processing",
                    response={},
                    **_timestamps(),
                ),
                False,
            )
        except IntegrityError:
            raise DomainError("request_in_progress", "The request is already being processed.", http_status=409)

    @staticmethod
    def finish(request_row: InterviewRequest, response: dict[str, Any]) -> None:
        InterviewRequest.update(status="completed", response=response, **_touch()).where(InterviewRequest.id == request_row.id).execute()

    @staticmethod
    def fail(request_row: InterviewRequest, error: DomainError) -> None:
        InterviewRequest.update(
            status="failed",
            response={"error": {"code": error.code, "message": error.message, "http_status": error.http_status}},
            **_touch(),
        ).where(InterviewRequest.id == request_row.id).execute()


def create_code_submission(
    tenant_id: str,
    user_id: str,
    session_id: str,
    round_id: str,
    language: str,
    source_code: str,
    *,
    operation_id: str | None = None,
) -> CodeSubmission:
    return CodeSubmission.create(
        id=get_uuid(),
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        round_id=round_id,
        language=language,
        source_code=source_code,
        operation_id=operation_id,
        execution_status="queued",
        visible_test_results=[],
        hidden_test_summary={},
        **_timestamps(),
    )


def complete_code_submission(submission: CodeSubmission, result: dict[str, Any], *, hidden: bool) -> CodeSubmission:
    output = str(result.get("compiler_output", ""))[:MAX_COMPILER_OUTPUT]
    if hidden and result.get("status") not in {"compile_error", "completed"}:
        output = "Hidden tests did not complete successfully."
    values = {
        "execution_status": result.get("status", "runner_error"),
        "passed_count": int(result.get("passed_count", 0)),
        "total_count": int(result.get("total_count", 0)),
        "runtime_ms": int(result.get("runtime_ms", 0)),
        "memory_kb": int(result.get("memory_kb", 0)),
        "compiler_output": output,
        "completed_at": utcnow(),
        **_touch(),
    }
    if hidden:
        values["hidden_test_summary"] = {
            "status": values["execution_status"],
            "passed_count": values["passed_count"],
            "total_count": values["total_count"],
        }
        values["visible_test_results"] = []
    else:
        values["visible_test_results"] = result.get("test_results", [])[:50]
        values["hidden_test_summary"] = {}
    CodeSubmission.update(**values).where(CodeSubmission.id == submission.id).execute()
    return CodeSubmission.get_by_id(submission.id)


def public_profile(profile: InterviewProfile) -> dict[str, Any]:
    data = _as_dict(profile)
    data["created_at"] = data.pop("create_date", None)
    data["updated_at"] = data.pop("update_date", None)
    data.pop("create_time", None)
    data.pop("update_time", None)
    data.pop("tenant_id", None)
    data.pop("user_id", None)
    return _public_json(data)


def public_resume(resume: InterviewResume) -> dict[str, Any]:
    """Candidate-facing resume DTO. Never includes the full resume text or chunk contents."""
    from api.apps.services.cs_interview.resume_service import resume_needs_extraction

    return _public_json(
        {
            "id": resume.id,
            "profile_id": resume.profile_id,
            "file_name": resume.file_name,
            "file_type": resume.file_type,
            "parse_status": resume.parse_status,
            "chunk_count": resume.chunk_count,
            "extraction": resume.extraction,
            "extracted_at": resume.extracted_at,
            "needs_extraction": resume_needs_extraction(resume),
            "created_at": resume.create_date,
            "updated_at": resume.update_date,
        }
    )


def public_job(job: InterviewJob, *, include_source: bool = False) -> dict[str, Any]:
    data = {
        "id": job.id,
        "name": job.name,
        "source_type": job.source_type,
        "extraction": job.extraction,
        "extraction_version": job.extraction_version,
        "extracted_at": job.extracted_at,
        "created_at": job.create_date,
        "updated_at": job.update_date,
    }
    if include_source:
        data["source_text"] = job.source_text
    return _public_json(data)


def public_knowledge_config(config: InterviewKnowledgeConfig) -> dict[str, Any]:
    data = _as_dict(config)
    data["created_at"] = data.pop("create_date", None)
    data["updated_at"] = data.pop("update_date", None)
    data.pop("create_time", None)
    data.pop("update_time", None)
    data.pop("tenant_id", None)
    data.pop("user_id", None)
    return _public_json(data)


def public_code_submission(submission: CodeSubmission) -> dict[str, Any]:
    return _public_json(
        {
            "id": submission.id,
            "session_id": submission.session_id,
            "round_id": submission.round_id,
            "language": submission.language,
            "execution_status": submission.execution_status,
            "visible_test_results": submission.visible_test_results,
            "hidden_test_summary": submission.hidden_test_summary,
            "passed_count": submission.passed_count,
            "total_count": submission.total_count,
            "runtime_ms": submission.runtime_ms,
            "memory_kb": submission.memory_kb,
            "compiler_output": submission.compiler_output,
            "created_at": submission.create_date,
            "completed_at": submission.completed_at,
        }
    )


def _round_project_targeting(round_) -> dict[str, Any]:
    """The project claim/context the round's current action is pursuing."""
    actions = round_.planner_actions or []
    for action in reversed(actions):
        if not isinstance(action, dict):
            continue
        project_id = str(action.get("target_project_id") or "")
        claim_id = str(action.get("target_claim_id") or "")
        if not project_id or not claim_id:
            continue
        supporting = action.get("supporting_state") or {}
        return {
            "target_project_id": project_id,
            "target_claim_id": claim_id,
            "project_dimension": str(action.get("project_dimension") or ""),
            "project_followup_depth": int(action.get("project_followup_depth") or 0),
            "claim_text": str(supporting.get("target_claim_fact") or "")[:500],
            "project_name": str(supporting.get("project_name") or "")[:255],
            "claim_type": str(supporting.get("claim_type") or "")[:64],
        }
    return {}


def _public_project_attack(session: InterviewSession) -> dict[str, Any]:
    """Non-sensitive attack-map summary for the session page.

    Never leaks planner weights or internal scoring points; only the frozen
    attack targets, the current claim and follow-up progress.
    """
    state = dict(session.current_candidate_state or {})
    attack_map = state.get("project_attack_map") or []
    claim_state = state.get("project_claim_state") or {}
    if not attack_map:
        return {"present": False}
    main = attack_map[0] if isinstance(attack_map[0], dict) else {}
    pending = [
        item
        for item in attack_map
        if isinstance(item, dict) and str(item.get("status") or "pending") in {"pending", "partial"}
    ]
    verified = sum(1 for row in claim_state.values() if isinstance(row, dict) and row.get("status") == "verified")
    return {
        "present": True,
        "project_id": main.get("project_id"),
        "project_name": main.get("project_name"),
        "attack_target_count": len(attack_map),
        "pending_target_count": len(pending),
        "verified_claim_count": verified,
        "claim_followup_limit": PROJECT_CLAIM_MAX_FOLLOWUPS,
    }


def public_round(round_: InterviewRound, *, include_evaluation: bool = True, claim_state: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence_sources = []
    for item in round_.retrieval_evidence or []:
        evidence_sources.append(
            {
                "evidence_id": item.get("evidence_id"),
                "dataset_id": item.get("dataset_id"),
                "document_name": item.get("document_name"),
                "source": item.get("metadata", {}).get("source"),
                "source_date": item.get("metadata", {}).get("source_date"),
                "quality_score": item.get("metadata", {}).get("quality_score"),
            }
        )
    candidate_answers = []
    for answer in round_.candidate_answers or []:
        candidate_answer = {
            "kind": answer.get("kind"),
            "answer": answer.get("answer"),
            "submitted_at": answer.get("submitted_at"),
        }
        evaluation = answer.get("evaluation")
        if include_evaluation and round_.status == RoundStatus.COMPLETED.value and isinstance(evaluation, dict):
            candidate_answer["evaluation"] = {
                "score": evaluation.get("score"),
                "verdict": evaluation.get("verdict"),
                "feedback": evaluation.get("feedback"),
            }
        candidate_answers.append(candidate_answer)
    data = {
        "id": round_.id,
        "session_id": round_.session_id,
        "sequence": round_.sequence,
        "status": round_.status,
        "question_id": round_.question_id,
        "category": round_.category,
        "topic": round_.topic,
        "question_type": round_.question_type,
        "difficulty": round_.difficulty,
        "question_kind": round_.question_kind or "adaptive",
        "competency_id": round_.competency_id or round_.topic,
        "question_text": round_.question_text,
        "candidate_answers": candidate_answers,
        "followup_questions": round_.followup_questions,
        "followup_count": round_.followup_count,
        "code_submission_id": round_.code_submission_id,
        "resume_probe": round_.resume_probe or None,
        "selected_action": round_.selected_action,
        "target_requirement_id": round_.target_requirement_id,
        "target_requirement": round_.target_requirement,
        "target_topic": round_.topic,
        "question_reason": round_.selection_reason,
        "project_target": _round_project_targeting(round_),
        "evidence_sources": evidence_sources,
        "asked_at": round_.asked_at,
        "answered_at": round_.answered_at,
        "completed_at": round_.completed_at,
        # Deterministic frontend classification: "project" only when the round
        # is truly bound to a project/claim/dimension; otherwise "foundation",
        # "anchor" or "coding".  A round is never labelled a project deep-dive
        # just because the session has an attack map.
        "question_category": question_category_for_round(dict(round_.__data__))["category"],
        "project_dive_downgraded": bool(
            (round_.question_validation or {}).get("project_dive", {}).get("downgraded_from_project")
        ),
        "pulled_by_project": question_category_for_round(dict(round_.__data__)).get("pulled_by_project"),
    }
    project_target = data.get("project_target") or {}
    if project_target and claim_state:
        target_id = (
            f"{project_target.get('target_project_id') or ''}::{project_target.get('target_claim_id') or ''}"
            f"::{project_target.get('project_dimension') or ''}"
        )
        row = claim_state.get(target_id) or {}
        project_target["verification_status"] = str(row.get("status") or "untested")
        project_target["attempt_count"] = int(row.get("attempt_count") or 0)
        project_target["followup_limit"] = PROJECT_CLAIM_MAX_FOLLOWUPS
        data["project_target"] = project_target
    if include_evaluation and round_.status == RoundStatus.COMPLETED.value:
        data.update(
            {
                "initial_score": round_.initial_score,
                "score": round_.score,
                "verdict": round_.verdict,
                "judge_confidence": round_.judge_confidence,
                "weak_point": round_.weak_point,
                "feedback": round_.feedback,
                "next_difficulty": round_.next_difficulty,
                "evaluation_summary": round_.evaluation_summary,
            }
        )
    return _public_json(data)


def public_report(report: InterviewReport) -> dict[str, Any]:
    data = _as_dict(report)
    data["created_at"] = data.pop("create_date", None)
    data["updated_at"] = data.pop("update_date", None)
    data.pop("create_time", None)
    data.pop("update_time", None)
    return _public_json(data)


def public_session(session: InterviewSession, *, include_rounds: bool = True) -> dict[str, Any]:
    data = {
        "id": session.id,
        "profile_id": session.profile_id,
        "knowledge_config_id": session.knowledge_config_id,
        "status": session.status,
        "current_difficulty": session.current_difficulty,
        "max_questions": session.max_questions,
        "max_followups": session.max_followups,
        "completed_question_count": session.completed_question_count,
        "current_round_sequence": session.current_round_sequence,
        "state_version": session.state_version,
        "prompt_version": session.prompt_version,
        "planner_version": session.planner_version,
        "started_at": session.started_at,
        "completed_at": session.completed_at,
        "aborted_at": session.aborted_at,
        "created_at": session.create_date,
        "updated_at": session.update_date,
        "failure_code": session.failure_code,
        "job": {
            "id": session.job_snapshot.get("id"),
            "name": session.job_snapshot.get("name"),
            "unmapped_requirement_ids": (session.job_snapshot.get("extraction") or {}).get("unmapped_requirement_ids", []),
        },
        "project_attack": _public_project_attack(session),
    }
    if include_rounds:
        claim_state = dict((session.current_candidate_state or {}).get("project_claim_state") or {})
        data["rounds"] = [public_round(row, claim_state=claim_state) for row in InterviewSessionRepository.rounds(session.id)]
        active = InterviewSessionRepository.active_round(session.id)
        data["active_round"] = public_round(active, include_evaluation=False, claim_state=claim_state) if active else None
    report = InterviewReport.get_or_none(InterviewReport.session_id == session.id)
    data["report"] = public_report(report) if report else None
    return _public_json(data)
