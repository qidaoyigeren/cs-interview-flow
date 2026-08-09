"""Authenticated REST and SSE surface for the CS interview application."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from functools import wraps
from typing import Any

from peewee import fn
from quart import Response, jsonify, request

from api.apps import current_user, login_required
from api.apps.services.cs_interview.domain import DomainError, SessionStatus, payload_hash, validate_answer, validate_code_request
from api.apps.services.cs_interview.evaluation import evaluate_file
from api.apps.services.cs_interview.experiment_service import (
    active_experiments_for,
    normalize_variant,
)
from api.apps.services.cs_interview.job_service import (
    create_job as create_job_service,
)
from api.apps.services.cs_interview.job_service import (
    create_job_from_file as create_job_from_file_service,
)
from api.apps.services.cs_interview.job_service import (
    extract_job as extract_job_service,
)
from api.apps.services.cs_interview.observability import SSE_ACTIVE, SSE_RECONNECT, metric_attributes
from api.apps.services.cs_interview.ops_service import (
    high_failure_questions,
    list_admin_sessions,
    list_feedback,
    quality_overview,
    record_review,
    session_audit,
    submit_feedback,
)
from api.apps.services.cs_interview.privacy import PrivacyService
from api.apps.services.cs_interview.quota import RedisQuotaManager, active_operation_count
from api.apps.services.cs_interview.reliability import TERMINAL_OPERATION_STATUSES, OperationType
from api.apps.services.cs_interview.replay import replay_session
from api.apps.services.cs_interview.resume_service import (
    create_profile_from_resume as create_profile_from_resume_service,
)
from api.apps.services.cs_interview.resume_service import (
    extract_resume as extract_resume_service,
)
from api.apps.services.cs_interview.resume_service import (
    upload_resume as upload_resume_service,
)
from api.apps.services.cs_interview.service import get_interview_application
from api.apps.services.cs_interview.worker import enqueue_operation
from api.db.db_models import (
    DB,
    InterviewExperiment,
    InterviewExperimentAssignment,
    InterviewModelCall,
    InterviewOperation,
    InterviewReport,
    InterviewResume,
    InterviewRound,
    InterviewSession,
)
from api.db.services.interview_operation_service import (
    InterviewOperationService,
    public_event,
    public_operation,
    session_operation_counts,
)
from api.db.services.interview_service import (
    InterviewJobService,
    InterviewKnowledgeService,
    InterviewProfileService,
    InterviewResumeService,
    InterviewSessionRepository,
    public_job,
    public_knowledge_config,
    public_profile,
    public_report,
    public_resume,
    public_session,
)
from api.utils.api_utils import get_request_json
from common.misc_utils import get_uuid

LOGGER = logging.getLogger(__name__)


def _identity() -> tuple[str, str]:
    # In the existing RAGFlow personal-workspace contract, the authenticated
    # user id is also the owning tenant id. Keeping both columns explicit makes
    # every domain lookup enforce both boundaries and leaves no user-only path.
    user_id = str(current_user.id)
    return user_id, user_id


def _ok(data: Any = None, *, status: int = 200):
    response = jsonify({"code": 0, "message": "success", "data": data})
    response.status_code = status
    return response


def _error(error: DomainError):
    response = jsonify(
        {
            "code": error.http_status,
            "message": error.message,
            "error": {"type": error.code},
        }
    )
    response.status_code = error.http_status
    return response


def require_ops_admin(*, sensitive: bool = False):
    """Admin gate with a second tier for sensitive fields.

    Base ops access requires is_superuser. Sensitive access additionally
    requires ``CS_INTERVIEW_OPS_SENSITIVE_ROLE`` (when set) and writes an audit
    row so every read of private detail is recorded.
    """
    if not bool(getattr(current_user, "is_superuser", False)):
        raise DomainError("forbidden", "Administrator access is required.", http_status=403)
    if sensitive:
        allowed = os.getenv("CS_INTERVIEW_OPS_SENSITIVE_ROLE", "")
        if allowed and allowed not in {str(current_user.id), str(getattr(current_user, "role", ""))}:
            raise DomainError("forbidden", "Sensitive interview data requires separate permission.", http_status=403)
        from api.db.services.interview_operation_service import audit as _audit

        _audit(str(current_user.id), str(current_user.id), "sensitive_access", "interview_data", str(current_user.id), "granted", {})


def _page_args() -> tuple[int, int]:
    try:
        page = max(1, int(request.args.get("page", "1")))
        page_size = max(1, min(100, int(request.args.get("page_size", "20"))))
    except ValueError as exc:
        raise DomainError("invalid_pagination", "page and page_size must be integers.") from exc
    return page, page_size


def domain_errors(function):
    @wraps(function)
    async def wrapper(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except DomainError as error:
            return _error(error)

    return wrapper


def _rate_limit(user_id: str) -> None:
    RedisQuotaManager().check_write_rate(user_id)


def _create_operation(
    tenant_id: str,
    user_id: str,
    session_id: str,
    request_id: str,
    operation_type: str,
    digest: str,
    payload: dict[str, Any],
    *,
    round_id: str | None = None,
) -> tuple[InterviewOperation, bool]:
    existing = InterviewOperation.get_or_none(
        (InterviewOperation.session_id == session_id) & (InterviewOperation.request_id == request_id)
    )
    if existing:
        operation, replay = InterviewOperationService.create(
            tenant_id,
            user_id,
            session_id,
            request_id,
            operation_type,
            digest,
            payload,
            round_id=round_id,
        )
        if operation.status not in TERMINAL_OPERATION_STATUSES:
            enqueue_operation(operation.id)
        return operation, replay
    from rag.utils.redis_conn import RedisDistributedLock

    lock = RedisDistributedLock(f"cs-interview:create-operation:{tenant_id}", timeout=10, blocking_timeout=2)
    try:
        acquired = lock.acquire()
    except Exception as exc:
        raise DomainError("quota_backend_unavailable", "The shared quota service is unavailable.", http_status=503) from exc
    if not acquired:
        raise DomainError("operation_creation_busy", "Operation capacity is being updated; retry shortly.", http_status=429)
    try:
        maximum = max(1, int(os.getenv("CS_INTERVIEW_MAX_TENANT_RUNNING_OPERATIONS", "8")))
        if active_operation_count(tenant_id) >= maximum:
            raise DomainError("tenant_operation_limit", "The tenant operation concurrency limit was reached.", http_status=429)
        operation, replay = InterviewOperationService.create(
            tenant_id,
            user_id,
            session_id,
            request_id,
            operation_type,
            digest,
            payload,
            round_id=round_id,
        )
    finally:
        lock.release()
    enqueue_operation(operation.id)
    return operation, replay


def _operation_result(operation: InterviewOperation, session, *, replay: bool):
    return {
        "operation": public_operation(operation),
        "session": public_session(session),
        "replayed": replay,
        "events_url": f"/api/v1/cs-interview/sessions/{session.id}/events?operation_id={operation.id}",
    }


def _create_code_operation(session_id: str, tenant_id: str, user_id: str, payload: dict[str, Any], *, hidden: bool) -> dict[str, Any]:
    language, source_code, _ = validate_code_request(payload.get("language"), payload.get("source_code"))
    request_id = str(payload.get("request_id", ""))
    session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
    digest = payload_hash({"language": language, "source_code": source_code, "hidden": hidden})
    existing = InterviewOperation.get_or_none(
        (InterviewOperation.session_id == session_id) & (InterviewOperation.request_id == request_id)
    )
    if existing:
        operation, replay = _create_operation(
            tenant_id,
            user_id,
            session.id,
            request_id,
            OperationType.EXECUTE_CODE.value,
            digest,
            {"language": language, "source_code": source_code, "hidden": hidden},
            round_id=existing.round_id,
        )
        return _operation_result(operation, session, replay=replay)
    if session.status != SessionStatus.AWAITING_ANSWER.value:
        raise DomainError("not_awaiting_answer", "Code can only run while the interview awaits an answer.", http_status=409)
    round_ = InterviewSessionRepository.active_round(session.id)
    if round_ is None or round_.category != "leetcode":
        raise DomainError("not_coding_round", "The active round is not an algorithm question.", http_status=409)
    operation, replay = _create_operation(
        tenant_id,
        user_id,
        session.id,
        request_id,
        OperationType.EXECUTE_CODE.value,
        digest,
        {"language": language, "source_code": source_code, "hidden": hidden},
        round_id=round_.id,
    )
    return _operation_result(operation, session, replay=replay)


def _persistent_sse(session_id: str, operation_id: str, after_sequence: int) -> Response:
    heartbeat_seconds = max(5, int(os.getenv("CS_INTERVIEW_SSE_HEARTBEAT_SECONDS", "15")))

    async def stream():
        cursor = max(0, after_sequence)
        last_heartbeat = asyncio.get_running_loop().time()
        SSE_ACTIVE.add(1, metric_attributes(status="connected"))
        try:
            yield "retry: 2000\n\n"
            while True:
                rows = InterviewOperationService.list_events(session_id, cursor, operation_id=operation_id, limit=100)
                for row in rows:
                    event = public_event(row)
                    cursor = int(event["sequence"])
                    yield (
                        f"id: {cursor}\n"
                        f"event: {event['event']}\n"
                        f"data: {json.dumps(event['data'], ensure_ascii=False, default=str)}\n\n"
                    )
                operation = InterviewOperation.get_or_none(InterviewOperation.id == operation_id)
                if operation is None or (operation.status in TERMINAL_OPERATION_STATUSES and not rows):
                    break
                now = asyncio.get_running_loop().time()
                if now - last_heartbeat >= heartbeat_seconds:
                    yield f": heartbeat {cursor}\n\n"
                    last_heartbeat = now
                await asyncio.sleep(0.5)
        finally:
            SSE_ACTIVE.add(-1, metric_attributes(status="connected"))

    response = Response(stream(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Connection"] = "keep-alive"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@manager.route("/cs-interview/jobs", methods=["GET"])  # noqa: F821
@login_required
async def list_jobs():
    tenant_id, user_id = _identity()
    return _ok([public_job(row) for row in InterviewJobService.list(tenant_id, user_id)])


@manager.route("/cs-interview/jobs", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def create_job():
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    payload = await get_request_json()
    if not isinstance(payload, dict):
        raise DomainError("invalid_job", "A JSON job description is required.")
    job = create_job_service(tenant_id, user_id, payload)
    return _ok(public_job(job, include_source=True), status=201)


@manager.route("/cs-interview/jobs/upload", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def upload_job():
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    files = await request.files
    if "file" not in files:
        raise DomainError("job_file_required", "A JD file is required.")
    form = await request.form
    job = create_job_from_file_service(
        tenant_id,
        user_id,
        files.getlist("file")[0],
        name=str(form.get("name") or "").strip() or None,
    )
    return _ok(public_job(job, include_source=True), status=201)


@manager.route("/cs-interview/jobs/<job_id>", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def get_job(job_id: str):
    tenant_id, user_id = _identity()
    return _ok(public_job(InterviewJobService.get(job_id, tenant_id, user_id), include_source=True))


@manager.route("/cs-interview/jobs/<job_id>/extract", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def extract_job(job_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    payload = await get_request_json()
    job = InterviewJobService.get(job_id, tenant_id, user_id)
    job = await extract_job_service(
        get_interview_application().runtime,
        tenant_id,
        job,
        force=bool(payload.get("force", False)) if isinstance(payload, dict) else False,
    )
    return _ok(public_job(job, include_source=True))


@manager.route("/cs-interview/jobs/<job_id>", methods=["PATCH"])  # noqa: F821
@login_required
@domain_errors
async def patch_job(job_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    payload = await get_request_json()
    if not isinstance(payload, dict) or not isinstance(payload.get("extraction"), dict):
        raise DomainError("invalid_job_extraction", "extraction must be a JSON object.")
    job = InterviewJobService.replace_extraction(job_id, tenant_id, user_id, payload["extraction"])
    return _ok(public_job(job, include_source=True))


@manager.route("/cs-interview/jobs/<job_id>", methods=["DELETE"])  # noqa: F821
@login_required
@domain_errors
async def delete_job(job_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    InterviewJobService.delete(job_id, tenant_id, user_id)
    return _ok({"deleted": True})


@manager.route("/cs-interview/profiles", methods=["GET"])  # noqa: F821
@login_required
async def list_profiles():
    tenant_id, user_id = _identity()
    return _ok([public_profile(row) for row in InterviewProfileService.list(tenant_id, user_id)])


@manager.route("/cs-interview/profiles", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def create_profile():
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    profile = InterviewProfileService.create(tenant_id, user_id, await get_request_json())
    return _ok(public_profile(profile), status=201)


@manager.route("/cs-interview/profiles/<profile_id>", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def get_profile(profile_id: str):
    tenant_id, user_id = _identity()
    return _ok(public_profile(InterviewProfileService.get(profile_id, tenant_id, user_id)))


@manager.route("/cs-interview/profiles/<profile_id>", methods=["PUT"])  # noqa: F821
@login_required
@domain_errors
async def update_profile(profile_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    profile = InterviewProfileService.update(profile_id, tenant_id, user_id, await get_request_json())
    return _ok(public_profile(profile))


@manager.route("/cs-interview/profiles/<profile_id>", methods=["DELETE"])  # noqa: F821
@login_required
@domain_errors
async def delete_profile(profile_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    InterviewProfileService.delete(profile_id, tenant_id, user_id)
    return _ok({"deleted": True})


@manager.route("/cs-interview/capabilities", methods=["GET"])  # noqa: F821
@login_required
async def list_capabilities():
    from api.apps.services.cs_interview.domain import ROLE_CAPABILITY_TREES

    return _ok(
        {
            role: [
                {
                    "id": topic.id,
                    "name": topic.name,
                    "weight": topic.weight,
                    "difficulties": topic.difficulties,
                    "question_types": topic.question_types,
                    "categories": topic.categories,
                    "minimum_coverage": topic.minimum_coverage,
                    "supports_code": topic.supports_code,
                    "retest_after": topic.retest_after,
                }
                for topic in topics
            ]
            for role, topics in ROLE_CAPABILITY_TREES.items()
        }
    )


@manager.route("/cs-interview/knowledge/datasets", methods=["GET"])  # noqa: F821
@login_required
async def list_knowledge_datasets():
    tenant_id, _ = _identity()
    return _ok(InterviewKnowledgeService.list_available(tenant_id))


@manager.route("/cs-interview/knowledge-config", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def get_knowledge_config():
    tenant_id, user_id = _identity()
    config_id = request.args.get("id")
    config = InterviewKnowledgeService.get(config_id, tenant_id, user_id) if config_id else InterviewKnowledgeService.latest(tenant_id, user_id)
    return _ok(public_knowledge_config(config) if config else None)


@manager.route("/cs-interview/knowledge-config", methods=["PUT"])  # noqa: F821
@login_required
@domain_errors
async def save_knowledge_config():
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    config = InterviewKnowledgeService.save(tenant_id, user_id, await get_request_json())
    return _ok(public_knowledge_config(config))


@manager.route("/cs-interview/knowledge-config/validate", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def validate_knowledge_config():
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    payload = await get_request_json()
    quality = InterviewKnowledgeService.validate_bindings(tenant_id, payload)
    return _ok(quality)


@manager.route("/cs-interview/sessions", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def list_sessions():
    tenant_id, user_id = _identity()
    try:
        page = max(1, int(request.args.get("page", "1")))
        page_size = max(1, min(100, int(request.args.get("page_size", "20"))))
    except ValueError as exc:
        raise DomainError("invalid_pagination", "page and page_size must be integers.") from exc
    rows = InterviewSessionRepository.list(tenant_id, user_id, page=page, page_size=page_size)
    return _ok([public_session(row, include_rounds=False) for row in rows])


@manager.route("/cs-interview/sessions", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def create_session():
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    payload = await get_request_json()
    profile_id = str(payload.get("profile_id", ""))
    config_id = str(payload.get("knowledge_config_id", ""))
    if not profile_id or not config_id:
        raise DomainError("invalid_session", "profile_id and knowledge_config_id are required.")
    from rag.utils.redis_conn import RedisDistributedLock

    # Serialize the count-and-create section across API replicas. The database
    # remains the source of truth for active sessions; Redis only closes the
    # otherwise unavoidable race between concurrent count queries.
    lock = RedisDistributedLock(f"cs-interview:create-session:{tenant_id}:{user_id}", timeout=10, blocking_timeout=2)
    try:
        acquired = lock.acquire()
    except Exception as exc:
        raise DomainError("quota_backend_unavailable", "The shared quota service is unavailable.", http_status=503) from exc
    if not acquired:
        raise DomainError("session_creation_busy", "Session capacity is being updated; retry shortly.", http_status=429)
    try:
        data = get_interview_application().create_session(
            tenant_id,
            user_id,
            profile_id,
            config_id,
        )
    finally:
        lock.release()
    return _ok(data, status=201)


@manager.route("/cs-interview/sessions/<session_id>", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def get_session(session_id: str):
    tenant_id, user_id = _identity()
    return _ok(public_session(InterviewSessionRepository.get(session_id, tenant_id, user_id)))


@manager.route("/cs-interview/operations/<operation_id>", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def get_operation(operation_id: str):
    tenant_id, user_id = _identity()
    return _ok(public_operation(InterviewOperationService.get(operation_id, tenant_id, user_id)))


@manager.route("/cs-interview/sessions/<session_id>/events", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def stream_session_events(session_id: str):
    tenant_id, user_id = _identity()
    InterviewSessionRepository.get(session_id, tenant_id, user_id)
    operation_id = str(request.args.get("operation_id", ""))
    if not operation_id:
        raise DomainError("operation_id_required", "operation_id is required.")
    operation = InterviewOperationService.get(operation_id, tenant_id, user_id)
    if operation.session_id != session_id:
        raise DomainError("operation_not_found", "Interview operation not found.", http_status=404)
    raw_after = request.headers.get("Last-Event-ID") or request.args.get("after_sequence", "0")
    try:
        after_sequence = max(0, int(raw_after))
    except (TypeError, ValueError) as exc:
        raise DomainError("invalid_event_sequence", "Last-Event-ID must be a non-negative integer.") from exc
    if after_sequence:
        SSE_RECONNECT.add(1, metric_attributes(status="resumed"))
    return _persistent_sse(session_id, operation_id, after_sequence)


@manager.route("/cs-interview/sessions/<session_id>/start", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def start_session(session_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    payload = await get_request_json()
    request_id = str(payload.get("request_id", ""))
    try:
        expected_version = int(payload["state_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError("invalid_state_version", "state_version is required.") from exc
    session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
    digest = payload_hash({"expected_version": expected_version})
    existing = InterviewOperation.get_or_none(
        (InterviewOperation.session_id == session_id) & (InterviewOperation.request_id == request_id)
    )
    if existing:
        operation, replay = _create_operation(
            tenant_id,
            user_id,
            session_id,
            request_id,
            OperationType.START_INTERVIEW.value,
            digest,
            {"state_version": expected_version, "prompt_version": session.prompt_version},
        )
        return _ok(_operation_result(operation, session, replay=replay), status=200 if operation.status in TERMINAL_OPERATION_STATUSES else 202)
    if session.status != SessionStatus.CREATED.value or session.state_version != expected_version:
        raise DomainError("state_conflict", "The session is not ready to start at this version.", http_status=409)
    operation, replay = _create_operation(
        tenant_id,
        user_id,
        session_id,
        request_id,
        OperationType.START_INTERVIEW.value,
        digest,
        {"state_version": expected_version, "prompt_version": session.prompt_version},
    )
    return _ok(_operation_result(operation, session, replay=replay), status=200 if operation.status in TERMINAL_OPERATION_STATUSES else 202)


@manager.route("/cs-interview/sessions/<session_id>/answers", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def submit_answer(session_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    payload = await get_request_json()
    request_id = str(payload.get("request_id", ""))
    try:
        expected_version = int(payload["state_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError("invalid_state_version", "state_version is required.") from exc
    answer = validate_answer(payload.get("answer"))
    session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
    digest = payload_hash({"answer": answer, "expected_version": expected_version})
    existing = InterviewOperation.get_or_none(
        (InterviewOperation.session_id == session_id) & (InterviewOperation.request_id == request_id)
    )
    if existing:
        operation, replay = _create_operation(
            tenant_id,
            user_id,
            session_id,
            request_id,
            OperationType.EVALUATE_ANSWER.value,
            digest,
            {"answer": answer, "state_version": expected_version, "prompt_version": session.prompt_version},
            round_id=existing.round_id,
        )
        return _ok(_operation_result(operation, session, replay=replay), status=200 if operation.status in TERMINAL_OPERATION_STATUSES else 202)
    if session.status != SessionStatus.AWAITING_ANSWER.value or session.state_version != expected_version:
        raise DomainError("state_conflict", "The session is not awaiting an answer at this version.", http_status=409)
    active_round = InterviewSessionRepository.active_round(session.id)
    if active_round is None:
        raise DomainError("active_round_missing", "No answerable interview round exists.", http_status=409)
    operation, replay = _create_operation(
        tenant_id,
        user_id,
        session_id,
        request_id,
        OperationType.EVALUATE_ANSWER.value,
        digest,
        {"answer": answer, "state_version": expected_version, "prompt_version": session.prompt_version},
        round_id=active_round.id,
    )
    return _ok(_operation_result(operation, session, replay=replay), status=200 if operation.status in TERMINAL_OPERATION_STATUSES else 202)


@manager.route("/cs-interview/sessions/<session_id>/code/run", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def run_visible_tests(session_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    payload = await get_request_json()
    return _ok(_create_code_operation(session_id, tenant_id, user_id, payload, hidden=False), status=202)


@manager.route("/cs-interview/sessions/<session_id>/code/submit", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def submit_code(session_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    payload = await get_request_json()
    return _ok(_create_code_operation(session_id, tenant_id, user_id, payload, hidden=True), status=202)


@manager.route("/cs-interview/sessions/<session_id>/abort", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def abort_session(session_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    payload = await get_request_json()
    try:
        state_version = int(payload["state_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError("invalid_state_version", "state_version is required.") from exc
    with DB.atomic():
        result = get_interview_application().abort(
            session_id,
            tenant_id,
            user_id,
            state_version,
            str(payload.get("request_id", "")),
        )
        InterviewOperationService.cancel_session(session_id, "user_abort")
    return _ok(result)


@manager.route("/cs-interview/sessions/<session_id>/report", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def get_report(session_id: str):
    tenant_id, user_id = _identity()
    session = InterviewSessionRepository.get(session_id, tenant_id, user_id)
    report = InterviewReport.get_or_none(InterviewReport.session_id == session.id)
    if report is None:
        raise DomainError("report_not_found", "The interview report is not available yet.", http_status=404)
    return _ok(public_report(report))


@manager.route("/cs-interview/sessions/<session_id>/personal-data", methods=["DELETE"])  # noqa: F821
@login_required
@domain_errors
async def anonymize_session(session_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    deletion = PrivacyService.request_deletion(tenant_id, user_id, "session", session_id)
    return _ok(deletion, status=202)


def _resume_preview(resume) -> dict[str, Any]:
    extraction = resume.extraction or {}
    skills = list(extraction.get("technology_stack") or [])
    if not skills:
        skills = [str(s.get("skill")) for s in (extraction.get("claimed_skills") or []) if s.get("skill")]
    project_names = [str(p.get("name")) for p in (extraction.get("projects") or []) if p.get("name")]
    return {"name": resume.file_name, "skills": skills[:20], "projectNames": project_names[:20]}


@manager.route("/cs-interview/resumes", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def upload_resume():
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    files = await request.files
    if "file" not in files:
        raise DomainError("resume_file_required", "A resume file is required.", http_status=400)
    file_obj = files.getlist("file")[0]
    resume = upload_resume_service(tenant_id, user_id, file_obj)
    return _ok(public_resume(resume), status=201)


@manager.route("/cs-interview/resumes", methods=["GET"])  # noqa: F821
@login_required
async def list_resumes():
    tenant_id, user_id = _identity()
    rows = InterviewResumeService.list(tenant_id, user_id)
    return _ok([public_resume(InterviewResumeService.sync_parse(row)) for row in rows])


@manager.route("/cs-interview/resumes/<resume_id>", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def get_resume(resume_id: str):
    tenant_id, user_id = _identity()
    resume = InterviewResumeService.get(resume_id, tenant_id, user_id)
    resume = InterviewResumeService.sync_parse(resume)
    data = public_resume(resume)
    data["preview"] = _resume_preview(resume)
    return _ok(data)


@manager.route("/cs-interview/resumes/<resume_id>/extract", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def extract_resume(resume_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    resume = InterviewResumeService.get(resume_id, tenant_id, user_id)
    resume = InterviewResumeService.sync_parse(resume)
    payload = await get_request_json()
    force = bool(payload.get("force", False)) if isinstance(payload, dict) else False
    resume = await extract_resume_service(get_interview_application().runtime, tenant_id, resume, force=force)
    return _ok(public_resume(resume))


@manager.route("/cs-interview/resumes/<resume_id>/profile", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def create_profile_from_resume(resume_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    resume = InterviewResumeService.get(resume_id, tenant_id, user_id)
    resume = InterviewResumeService.sync_parse(resume)
    payload = await get_request_json()
    profile = create_profile_from_resume_service(tenant_id, user_id, resume, payload if isinstance(payload, dict) else {})
    return _ok(public_profile(profile), status=201)


@manager.route("/cs-interview/resumes/<resume_id>", methods=["PATCH"])  # noqa: F821
@login_required
@domain_errors
async def patch_resume(resume_id: str):
    from api.apps.services.cs_interview.domain import utcnow as domain_utcnow
    from api.apps.services.cs_interview.domain import validate_resume_extraction

    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    resume = InterviewResumeService.get(resume_id, tenant_id, user_id)
    payload = await get_request_json()
    if isinstance(payload, dict) and isinstance(payload.get("extraction"), dict):
        validated = validate_resume_extraction(payload["extraction"])
        InterviewResume.update(extraction=validated, extracted_at=domain_utcnow(), parse_status="parsed").where(
            (InterviewResume.id == resume.id) & (InterviewResume.tenant_id == tenant_id) & (InterviewResume.user_id == user_id)
        ).execute()
        resume = InterviewResumeService.get(resume_id, tenant_id, user_id)
    return _ok(public_resume(resume))


@manager.route("/cs-interview/resumes/<resume_id>", methods=["DELETE"])  # noqa: F821
@login_required
@domain_errors
async def delete_resume(resume_id: str):
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    deletion = PrivacyService.request_deletion(tenant_id, user_id, "resume", resume_id)
    return _ok({"deleted": True, "deletion_request": deletion})


@manager.route("/cs-interview/privacy/deletions", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def request_privacy_deletion():
    tenant_id, user_id = _identity()
    _rate_limit(user_id)
    payload = await get_request_json()
    deletion = PrivacyService.request_deletion(
        tenant_id,
        user_id,
        str(payload.get("resource_type", "")),
        str(payload.get("resource_id", "")),
    )
    return _ok(deletion, status=202)


@manager.route("/cs-interview/privacy/deletions/<deletion_id>", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def get_privacy_deletion(deletion_id: str):
    tenant_id, user_id = _identity()
    return _ok(PrivacyService.deletion_status(deletion_id, tenant_id, user_id))


@manager.route("/cs-interview/privacy/export", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def export_privacy_data():
    tenant_id, user_id = _identity()
    return _ok(PrivacyService.export(tenant_id, user_id))


@manager.route("/cs-interview/admin/audit", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def admin_audit():
    if not bool(getattr(current_user, "is_superuser", False)):
        raise DomainError("forbidden", "Administrator access is required.", http_status=403)
    tenant_id, _ = _identity()
    try:
        page = max(1, int(request.args.get("page", "1")))
        page_size = max(1, min(100, int(request.args.get("page_size", "50"))))
    except ValueError as exc:
        raise DomainError("invalid_pagination", "page and page_size must be integers.") from exc
    return _ok(PrivacyService.audit_rows(tenant_id, page=page, page_size=page_size))


@manager.route("/cs-interview/admin/usage", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def admin_usage():
    if not bool(getattr(current_user, "is_superuser", False)):
        raise DomainError("forbidden", "Administrator access is required.", http_status=403)
    tenant_id, _ = _identity()
    totals = (
        InterviewSession.select(
            fn.COALESCE(fn.SUM(InterviewSession.total_prompt_tokens), 0).alias("prompt_tokens"),
            fn.COALESCE(fn.SUM(InterviewSession.total_completion_tokens), 0).alias("completion_tokens"),
            fn.COALESCE(fn.SUM(InterviewSession.total_estimated_cost), 0).alias("estimated_cost"),
            fn.COALESCE(fn.SUM(InterviewSession.llm_request_count), 0).alias("llm_requests"),
            fn.COALESCE(fn.SUM(InterviewSession.retrieval_request_count), 0).alias("retrieval_requests"),
            fn.MAX(InterviewSession.cost_unknown).alias("cost_unknown"),
        )
        .where(InterviewSession.tenant_id == tenant_id)
        .dicts()
        .get()
    )
    model_rows = (
        InterviewModelCall.select(
            InterviewModelCall.model,
            InterviewModelCall.stage,
            fn.COUNT(InterviewModelCall.id).alias("request_count"),
            fn.COALESCE(fn.SUM(InterviewModelCall.prompt_tokens), 0).alias("prompt_tokens"),
            fn.COALESCE(fn.SUM(InterviewModelCall.completion_tokens), 0).alias("completion_tokens"),
            fn.COALESCE(fn.SUM(InterviewModelCall.estimated_cost), 0).alias("estimated_cost"),
            fn.MAX(InterviewModelCall.cost_unknown).alias("cost_unknown"),
        )
        .where(InterviewModelCall.tenant_id == tenant_id)
        .group_by(InterviewModelCall.model, InterviewModelCall.stage)
        .dicts()
    )
    return _ok({"totals": totals, "by_model_stage": list(model_rows), "operations": session_operation_counts(tenant_id)})


@manager.route("/cs-interview/admin/quality", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def admin_quality():
    if not bool(getattr(current_user, "is_superuser", False)):
        raise DomainError("forbidden", "Administrator access is required.", http_status=403)
    tenant_id, user_id = _identity()
    config = InterviewKnowledgeService.latest(tenant_id, user_id)
    quality = InterviewKnowledgeService.revalidate(config) if config else None
    runner_healthy = await get_interview_application().runner.health()
    fixture_path = os.getenv("CS_INTERVIEW_EVAL_FIXTURE", "test/fixtures/cs_interview/offline_eval.json")
    try:
        evaluation = evaluate_file(fixture_path).as_dict()
    except (OSError, ValueError, KeyError):
        evaluation = None
    return _ok(
        {
            "knowledge_config": public_knowledge_config(config) if config else None,
            "quality": quality,
            "runner_healthy": runner_healthy,
            "offline_evaluation": evaluation,
        }
    )


@manager.route("/cs-interview/admin/quality/overview", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def admin_quality_overview():
    require_ops_admin()
    tenant_id, _ = _identity()
    try:
        since_hours = max(1, min(24 * 90, int(request.args.get("since_hours", "24"))))
    except ValueError as exc:
        raise DomainError("invalid_window", "since_hours must be an integer.") from exc
    return _ok(quality_overview(tenant_id=tenant_id, since_hours=since_hours))


@manager.route("/cs-interview/admin/sessions", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def admin_list_sessions():
    require_ops_admin()
    tenant_id, _ = _identity()
    page, page_size = _page_args()
    status = request.args.get("status") or None
    return _ok(list_admin_sessions(tenant_id=tenant_id, page=page, page_size=page_size, status=status))


@manager.route("/cs-interview/admin/sessions/<session_id>/audit", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def admin_session_audit(session_id: str):
    require_ops_admin()
    tenant_id, _ = _identity()
    return _ok(session_audit(session_id, tenant_id))


@manager.route("/cs-interview/admin/sessions/<session_id>/replay", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def admin_session_replay(session_id: str):
    require_ops_admin()
    tenant_id, _ = _identity()
    payload = await get_request_json()
    planner_version = str((payload or {}).get("planner_version") or "latest")
    session = InterviewSession.get_or_none((InterviewSession.id == session_id) & (InterviewSession.tenant_id == tenant_id))
    if session is None:
        raise DomainError("session_not_found", "Session not found.", http_status=404)
    rounds = list(InterviewRound.select().where(InterviewRound.session_id == session_id).order_by(InterviewRound.sequence))
    return _ok(replay_session(session, rounds, planner_version=planner_version))


@manager.route("/cs-interview/admin/questions", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def admin_questions():
    require_ops_admin()
    tenant_id, _ = _identity()
    page, page_size = _page_args()
    return _ok(high_failure_questions(tenant_id=tenant_id, page=page, page_size=page_size))


@manager.route("/cs-interview/admin/review", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def admin_review():
    require_ops_admin()
    tenant_id, user_id = _identity()
    payload = await get_request_json()
    resource_type = str((payload or {}).get("resource_type") or "")
    resource_id = str((payload or {}).get("resource_id") or "")
    action = str((payload or {}).get("action") or "")
    comment = str((payload or {}).get("comment") or "")
    return _ok(record_review(reviewer_id_hash=user_id, resource_type=resource_type, resource_id=resource_id, action=action, comment=comment, tenant_id=tenant_id))


@manager.route("/cs-interview/admin/feedback", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def admin_feedback():
    require_ops_admin()
    tenant_id, _ = _identity()
    page, page_size = _page_args()
    return _ok(list_feedback(tenant_id=tenant_id, page=page, page_size=page_size))


@manager.route("/cs-interview/sessions/<session_id>/feedback", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def session_feedback(session_id: str):
    tenant_id, user_id = _identity()
    payload = await get_request_json()
    kind = str((payload or {}).get("kind") or "")
    message = str((payload or {}).get("message") or "")
    if not message.strip():
        raise DomainError("invalid_feedback", "Feedback message must not be empty.", http_status=400)
    versions = {
        "round_id": (payload or {}).get("round_id"),
        "evidence_id": (payload or {}).get("evidence_id"),
    }
    return _ok(submit_feedback(tenant_id=tenant_id, user_id=user_id, session_id=session_id, kind=kind, message=message, **versions))


@manager.route("/cs-interview/admin/experiments", methods=["GET", "POST"])  # noqa: F821
@login_required
@domain_errors
async def admin_experiments():
    require_ops_admin()
    tenant_id, user_id = _identity()
    if request.method == "GET":
        page, page_size = _page_args()
        rows = (
            InterviewExperiment.select()
            .where(InterviewExperiment.tenant_id == tenant_id)
            .order_by(InterviewExperiment.create_time.desc())
            .paginate(page, page_size)
        )
        return _ok(
            {
                "items": [{"id": row.id, "name": row.name, "status": row.status, "traffic_percentage": row.traffic_percentage, "created_by": row.created_by} for row in rows],
                "active": [
                    {"id": row.id, "name": row.name, "traffic_percentage": row.traffic_percentage}
                    for row in active_experiments_for(tenant_id)
                ],
            }
        )
    payload = await get_request_json()
    name = str((payload or {}).get("name") or "")
    if not name:
        raise DomainError("invalid_experiment", "Experiment name is required.", http_status=400)
    status = str((payload or {}).get("status") or "draft")
    if status not in {"draft", "gray"}:
        raise DomainError("invalid_experiment", "A new experiment must be draft or gray.", http_status=400)
    control_variant = normalize_variant(dict((payload or {}).get("control_variant") or {}), default_variant_id="control")
    candidate_variants = [
        normalize_variant(dict(item or {}), default_variant_id=f"candidate-{index + 1}")
        for index, item in enumerate(list((payload or {}).get("candidate_variants") or []))
    ]
    traffic_percentage = max(0, min(100, int((payload or {}).get("traffic_percentage") or 0)))
    if traffic_percentage and not candidate_variants:
        raise DomainError("invalid_experiment", "Candidate traffic requires at least one candidate variant.", http_status=400)
    row = InterviewExperiment.create(
        id=get_uuid(),
        tenant_id=tenant_id,
        name=name,
        status=status,
        control_variant=control_variant,
        candidate_variants=candidate_variants,
        traffic_percentage=traffic_percentage,
        target_tenants=list((payload or {}).get("target_tenants") or []),
        guardrail_metrics=list((payload or {}).get("guardrail_metrics") or []),
        success_metrics=dict((payload or {}).get("success_metrics") or {}),
        created_by=user_id,
    )
    return _ok({"id": row.id, "status": row.status}, status=201)


@manager.route("/cs-interview/admin/experiments/<experiment_id>/stop", methods=["POST"])  # noqa: F821
@login_required
@domain_errors
async def admin_experiment_stop(experiment_id: str):
    require_ops_admin()
    tenant_id, user_id = _identity()
    row = InterviewExperiment.get_or_none(
        (InterviewExperiment.id == experiment_id) & (InterviewExperiment.tenant_id == tenant_id)
    )
    if row is None:
        raise DomainError("experiment_not_found", "Experiment not found.", http_status=404)
    InterviewExperiment.update(status="stopped").where(
        (InterviewExperiment.id == experiment_id) & (InterviewExperiment.tenant_id == tenant_id)
    ).execute()
    from api.db.services.interview_operation_service import audit as _audit

    _audit(tenant_id, user_id, "experiment_stop", "interview_experiment", experiment_id, "stopped", {})
    return _ok({"id": experiment_id, "status": "stopped"})


@manager.route("/cs-interview/admin/experiments/<experiment_id>/assignments", methods=["GET"])  # noqa: F821
@login_required
@domain_errors
async def admin_experiment_assignments(experiment_id: str):
    require_ops_admin()
    tenant_id, _ = _identity()
    experiment = InterviewExperiment.get_or_none(
        (InterviewExperiment.id == experiment_id) & (InterviewExperiment.tenant_id == tenant_id)
    )
    if experiment is None:
        raise DomainError("experiment_not_found", "Experiment not found.", http_status=404)
    page, page_size = _page_args()
    rows = (
        InterviewExperimentAssignment.select()
        .where(
            (InterviewExperimentAssignment.experiment_id == experiment_id)
            & (InterviewExperimentAssignment.tenant_id == tenant_id)
        )
        .order_by(InterviewExperimentAssignment.create_time.desc())
        .paginate(page, page_size)
    )
    return _ok([{"session_id": row.session_id, "variant_id": row.variant_id, "bucket_hash": row.bucket_hash, "assigned_at": row.assigned_at} for row in rows])
