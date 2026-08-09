"""Privacy deletion, export, audit, and configurable retention lifecycle."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from api.apps.services.cs_interview.domain import DomainError, utcnow
from api.apps.services.cs_interview.resume_service import delete_resume
from api.db.db_models import (
    CodeSubmission,
    InterviewAuditLog,
    InterviewDeletionRequest,
    InterviewEvent,
    InterviewJob,
    InterviewModelCall,
    InterviewOperation,
    InterviewOperationCheckpoint,
    InterviewProfile,
    InterviewRequest,
    InterviewResume,
    InterviewRound,
    InterviewSession,
    InterviewTraceEvent,
)
from api.db.services.interview_operation_service import audit, public_operation
from api.db.services.interview_service import (
    InterviewResumeService,
    InterviewSessionRepository,
    _public_json,
    _timestamps,
    _touch,
    public_job,
    public_profile,
    public_resume,
    public_session,
)
from common.misc_utils import get_uuid


def _days(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


@dataclass(frozen=True)
class RetentionPolicy:
    raw_resume_jd_days: int
    answer_code_days: int
    session_report_days: int
    idempotency_days: int
    event_days: int
    audit_days: int
    trace_event_days: int

    @classmethod
    def from_env(cls) -> RetentionPolicy:
        return cls(
            raw_resume_jd_days=_days("CS_INTERVIEW_RAW_DOCUMENT_RETENTION_DAYS", 365),
            answer_code_days=_days("CS_INTERVIEW_ANSWER_CODE_RETENTION_DAYS", 365),
            session_report_days=_days("CS_INTERVIEW_SESSION_REPORT_RETENTION_DAYS", 730),
            idempotency_days=_days("CS_INTERVIEW_IDEMPOTENCY_RETENTION_DAYS", 7),
            event_days=_days("CS_INTERVIEW_EVENT_RETENTION_DAYS", 30),
            audit_days=_days("CS_INTERVIEW_AUDIT_RETENTION_DAYS", 730),
            trace_event_days=_days("CS_INTERVIEW_TRACE_EVENT_RETENTION_DAYS", 180),
        )


def _deletion_dto(row: InterviewDeletionRequest) -> dict[str, Any]:
    return _public_json(
        {
            "id": row.id,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "status": row.status,
            "error_code": row.error_code,
            "completed_at": row.completed_at,
            "created_at": row.create_date,
            "updated_at": row.update_date,
        }
    )


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _formula_safe(value: Any) -> Any:
    """Neutralize spreadsheet formula injection in CSV/JSON export payloads.

    Any string cell beginning with a formula prefix (``= + - @``) or a tab/newline
    is prefixed with a single quote so opening the export in a spreadsheet never
    executes a formula.  Applied recursively to exported structures.
    """
    if isinstance(value, str):
        stripped = value.lstrip(" \t\r")
        if stripped.startswith(_FORMULA_PREFIXES) and len(stripped) > 1:
            return "'" + value
        return value
    if isinstance(value, dict):
        return {key: _formula_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_formula_safe(item) for item in value]
    return value


class PrivacyService:
    @staticmethod
    def request_deletion(tenant_id: str, user_id: str, resource_type: str, resource_id: str) -> dict[str, Any]:
        if resource_type not in {"resume", "session"}:
            raise DomainError("invalid_deletion_resource", "Only resume and session deletion requests are supported.")
        row = InterviewDeletionRequest.create(
            id=get_uuid(),
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            status="running",
            **_timestamps(),
        )
        try:
            if resource_type == "resume":
                resume = InterviewResumeService.get(resource_id, tenant_id, user_id)
                delete_resume(tenant_id, user_id, resume)
            else:
                from api.db.services.interview_operation_service import InterviewOperationService

                InterviewOperationService.cancel_session(resource_id, "privacy_deletion")
                InterviewSessionRepository.anonymize(resource_id, tenant_id, user_id)
            InterviewDeletionRequest.update(status="completed", completed_at=utcnow(), **_touch()).where(
                InterviewDeletionRequest.id == row.id
            ).execute()
            audit(tenant_id, user_id, "privacy_delete", resource_type, resource_id, "completed", {"deletion_request_id": row.id})
        except DomainError as error:
            InterviewDeletionRequest.update(status="failed", error_code=error.code, completed_at=utcnow(), **_touch()).where(
                InterviewDeletionRequest.id == row.id
            ).execute()
            audit(tenant_id, user_id, "privacy_delete", resource_type, resource_id, "failed", {"error_code": error.code})
            raise
        return _deletion_dto(InterviewDeletionRequest.get_by_id(row.id))

    @staticmethod
    def deletion_status(deletion_id: str, tenant_id: str, user_id: str) -> dict[str, Any]:
        row = InterviewDeletionRequest.get_or_none(
            (InterviewDeletionRequest.id == deletion_id)
            & (InterviewDeletionRequest.tenant_id == tenant_id)
            & (InterviewDeletionRequest.user_id == user_id)
        )
        if row is None:
            raise DomainError("deletion_not_found", "Deletion request not found.", http_status=404)
        return _deletion_dto(row)

    @staticmethod
    def export(tenant_id: str, user_id: str) -> dict[str, Any]:
        sessions = list(
            InterviewSession.select().where(
                (InterviewSession.tenant_id == tenant_id) & (InterviewSession.user_id == user_id)
            )
        )
        session_ids = [row.id for row in sessions]
        submissions = list(
            CodeSubmission.select().where(
                (CodeSubmission.tenant_id == tenant_id) & (CodeSubmission.user_id == user_id)
            )
        )
        result = {
            "exported_at": utcnow(),
            "profiles": [public_profile(row) for row in InterviewProfile.select().where((InterviewProfile.tenant_id == tenant_id) & (InterviewProfile.user_id == user_id))],
            "resumes": [public_resume(row) for row in InterviewResume.select().where((InterviewResume.tenant_id == tenant_id) & (InterviewResume.user_id == user_id))],
            "jobs": [public_job(row, include_source=True) for row in InterviewJob.select().where((InterviewJob.tenant_id == tenant_id) & (InterviewJob.user_id == user_id))],
            "sessions": [public_session(row) for row in sessions],
            "code_submissions": [
                {
                    "id": row.id,
                    "session_id": row.session_id,
                    "round_id": row.round_id,
                    "language": row.language,
                    "source_code": row.source_code,
                    "execution_status": row.execution_status,
                    "created_at": row.create_date,
                }
                for row in submissions
            ],
            "operations": [
                public_operation(row)
                for row in InterviewOperation.select().where(
                    (InterviewOperation.tenant_id == tenant_id) & (InterviewOperation.user_id == user_id)
                )
            ],
        }
        audit(tenant_id, user_id, "privacy_export", "user", user_id, "completed", {"session_count": len(session_ids)})
        # Neutralize spreadsheet formula injection before any CSV/JSON export.
        return _public_json(_formula_safe(result))

    @staticmethod
    def audit_rows(tenant_id: str, *, page: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
        rows = (
            InterviewAuditLog.select()
            .where(InterviewAuditLog.tenant_id == tenant_id)
            .order_by(InterviewAuditLog.create_time.desc())
            .paginate(max(1, page), max(1, min(100, page_size)))
        )
        return [
            _public_json(
                {
                    "id": row.id,
                    "actor_id_hash": row.actor_id_hash,
                    "action": row.action,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "outcome": row.outcome,
                    "metadata": row.metadata,
                    "created_at": row.create_date,
                }
            )
            for row in rows
        ]

    @staticmethod
    def cleanup(policy: RetentionPolicy | None = None, *, now: datetime | None = None) -> dict[str, int]:
        policy = policy or RetentionPolicy.from_env()
        now = now or datetime.now(UTC).replace(tzinfo=None)

        def millis(value: datetime) -> int:
            return int(value.timestamp() * 1000)
        event_count = InterviewEvent.delete().where(
            InterviewEvent.create_time < millis(now - timedelta(days=policy.event_days))
        ).execute()
        request_count = InterviewRequest.delete().where(
            InterviewRequest.create_time < millis(now - timedelta(days=policy.idempotency_days))
        ).execute()
        audit_count = InterviewAuditLog.delete().where(
            InterviewAuditLog.create_time < millis(now - timedelta(days=policy.audit_days))
        ).execute()
        prompt_count = InterviewModelCall.update(prompt_snapshot={"redacted": True}, **_touch()).where(
            InterviewModelCall.create_time < millis(now - timedelta(days=policy.answer_code_days))
        ).execute()
        checkpoint_count = InterviewOperationCheckpoint.delete().where(
            InterviewOperationCheckpoint.create_time < millis(now - timedelta(days=policy.answer_code_days))
        ).execute()
        trace_event_count = InterviewTraceEvent.delete().where(
            InterviewTraceEvent.create_time < millis(now - timedelta(days=policy.trace_event_days))
        ).execute()
        code_count = CodeSubmission.update(source_code="[retention deleted]", **_touch()).where(
            CodeSubmission.create_time < millis(now - timedelta(days=policy.answer_code_days))
        ).execute()
        answer_count = 0
        old_sessions = InterviewSession.select().where(
            InterviewSession.create_time < millis(now - timedelta(days=policy.answer_code_days))
        )
        for session in old_sessions:
            answer_count += InterviewRound.update(candidate_answers=[], answer_state={}, **_touch()).where(
                InterviewRound.session_id == session.id
            ).execute()
        job_count = InterviewJob.update(source_text="[retention deleted]", **_touch()).where(
            InterviewJob.create_time < millis(now - timedelta(days=policy.raw_resume_jd_days))
        ).execute()
        resume_count = 0
        old_resumes = list(
            InterviewResume.select().where(
                InterviewResume.create_time < millis(now - timedelta(days=policy.raw_resume_jd_days))
            )
        )
        for resume in old_resumes:
            try:
                delete_resume(resume.tenant_id, resume.user_id, resume)
                resume_count += 1
            except DomainError:
                audit(
                    resume.tenant_id,
                    "retention-worker",
                    "retention_delete",
                    "resume",
                    resume.id,
                    "failed",
                    {"error_code": "resume_cleanup_failed"},
                )
        session_count = 0
        old_sessions = list(
            InterviewSession.select().where(
                InterviewSession.create_time < millis(now - timedelta(days=policy.session_report_days))
            )
        )
        for session in old_sessions:
            if (session.profile_snapshot or {}).get("redacted"):
                continue
            from api.db.services.interview_operation_service import InterviewOperationService

            InterviewOperationService.cancel_session(session.id, "retention_expired")
            InterviewSessionRepository.anonymize(session.id, session.tenant_id, session.user_id)
            session_count += 1
        return {
            "events": event_count,
            "requests": request_count,
            "audit": audit_count,
            "prompt_snapshots": prompt_count,
            "operation_checkpoints": checkpoint_count,
            "code_submissions": code_count,
            "round_answers": answer_count,
            "job_sources": job_count,
            "resumes": resume_count,
            "sessions": session_count,
            "trace_events": trace_event_count,
        }
