import asyncio
import json
import sys
import types

import pytest
from peewee import IntegrityError, SqliteDatabase

import api.apps.services.cs_interview.service as application_service
import api.db.services.interview_operation_service as operation_persistence
import api.db.services.interview_service as persistence
from api.apps.services.cs_interview import resume_service
from api.apps.services.cs_interview.domain import DomainError, initial_candidate_state
from api.apps.services.cs_interview.service import InterviewApplication
from api.db.db_models import (
    CodeSubmission,
    InterviewEvent,
    InterviewExperiment,
    InterviewExperimentAssignment,
    InterviewJob,
    InterviewKnowledgeConfig,
    InterviewModelCall,
    InterviewOperation,
    InterviewOperationCheckpoint,
    InterviewProfile,
    InterviewReport,
    InterviewRequest,
    InterviewResume,
    InterviewReviewAction,
    InterviewRound,
    InterviewSession,
)
from api.db.services.interview_service import (
    InterviewJobService,
    InterviewKnowledgeService,
    InterviewRequestService,
    InterviewSessionRepository,
    public_round,
    public_session,
)

MODELS = [
    InterviewJob,
    InterviewProfile,
    InterviewResume,
    InterviewKnowledgeConfig,
    InterviewSession,
    InterviewRound,
    InterviewReport,
    CodeSubmission,
    InterviewRequest,
    InterviewOperation,
    InterviewEvent,
    InterviewOperationCheckpoint,
    InterviewModelCall,
    InterviewExperiment,
    InterviewExperimentAssignment,
    InterviewReviewAction,
]


@pytest.fixture()
def interview_db(monkeypatch):
    database = SqliteDatabase(":memory:")
    with database.bind_ctx(MODELS, bind_refs=False, bind_backrefs=False):
        database.create_tables(MODELS)
        monkeypatch.setattr(persistence, "DB", database)
        monkeypatch.setattr(application_service, "DB", database)
        monkeypatch.setattr(resume_service, "DB", database)
        monkeypatch.setattr(operation_persistence, "DB", database)
        try:
            yield database
        finally:
            database.drop_tables(MODELS)
            database.close()


def _timestamps():
    return {
        "create_time": 1,
        "create_date": "2026-08-07 00:00:00",
        "update_time": 1,
        "update_date": "2026-08-07 00:00:00",
    }


def test_three_knowledge_bindings_must_be_independent_and_parsed(monkeypatch):
    duplicate = {
        "interview_experience_dataset_id": "dataset-1",
        "leetcode_dataset_id": "dataset-1",
        "fundamentals_dataset_id": "dataset-3",
    }
    with pytest.raises(DomainError, match="must be different"):
        InterviewKnowledgeService.validate_bindings("tenant-1", duplicate)

    calls = []

    def inspect(dataset_id, tenant_id, content_type):
        calls.append((dataset_id, tenant_id, content_type))
        return {
            "id": dataset_id,
            "name": dataset_id,
            "parsed": dataset_id != "dataset-unparsed",
            "embedding_model": "embedding/test",
        }

    monkeypatch.setattr(persistence, "inspect_dataset", inspect)
    bindings = {
        "interview_experience_dataset_id": "dataset-experience",
        "leetcode_dataset_id": "dataset-leetcode",
        "fundamentals_dataset_id": "dataset-fundamentals",
    }
    InterviewKnowledgeService.validate_bindings("tenant-1", bindings)
    assert calls == [
        ("dataset-experience", "tenant-1", "interview_experience"),
        ("dataset-leetcode", "tenant-1", "leetcode"),
        ("dataset-fundamentals", "tenant-1", "fundamentals"),
    ]

    bindings["fundamentals_dataset_id"] = "dataset-unparsed"
    with pytest.raises(DomainError, match="unparsed or failed"):
        InterviewKnowledgeService.validate_bindings("tenant-1", bindings)


def _session(status="created"):
    InterviewProfile.create(
        id="profile-1",
        tenant_id="tenant-1",
        user_id="user-1",
        name="test",
        target_role="go_backend",
        target_level="mid",
        technology_stack=["Go"],
        focus_topics=[],
        excluded_topics=[],
        initial_difficulty="medium",
        preferred_categories=["baguwen"],
        question_count=2,
        max_followups=2,
        **_timestamps(),
    )
    InterviewKnowledgeConfig.create(
        id="config-1",
        tenant_id="tenant-1",
        user_id="user-1",
        interview_experience_dataset_id="dataset-1",
        leetcode_dataset_id="dataset-2",
        fundamentals_dataset_id="dataset-3",
        retrieval_config_snapshot={},
        metadata_quality_snapshot={},
        enabled=True,
        **_timestamps(),
    )
    return InterviewSession.create(
        id="session-1",
        tenant_id="tenant-1",
        user_id="user-1",
        profile_id="profile-1",
        knowledge_config_id="config-1",
        status=status,
        current_difficulty="medium",
        max_questions=2,
        max_followups=2,
        completed_question_count=0,
        current_round_sequence=0,
        state_version=0,
        model_config_snapshot={},
        knowledge_base_versions={},
        performance_snapshot={},
        **_timestamps(),
    )


def _snapshot(question_id="q-1"):
    return {
        "question_id": question_id,
        "category": "baguwen",
        "topic": "go.runtime",
        "question_type": "theory",
        "difficulty": "medium",
        "question_text": "Explain Go channel closing behavior.",
        "reference_answer": "A private answer that must not be serialized.",
        "evaluation_rubric": ["private point"],
        "retrieval_query": "structured query",
        "retrieval_evidence": [
            {
                "evidence_id": "e-1",
                "dataset_id": "dataset-3",
                "document_name": "Synthetic source",
                "content": "private original content",
                "metadata": {"source": "fixture", "source_date": "2026-01-01", "quality_score": 1},
            }
        ],
        "evidence_versions": [{"evidence_id": "e-1", "dataset_id": "dataset-3"}],
        "source_version": "v1",
        "prompt_version": "p1",
        "model_version": "m1",
        "planner_action": {
            "selected_action": "verify_jd_requirement",
            "target_requirement_id": "req-1",
            "target_topic": "go.runtime",
            "reason": "Verify the JD requirement.",
            "supporting_state": {},
            "planner_version": "cs-interview-planner-v1",
            "followup_focus": "",
            "target_difficulty": "medium",
            "preferred_question_type": "theory",
        },
        "question_validation": {
            "jd_relevance": True,
            "topic_consistency": True,
            "difficulty_consistency": True,
            "reference_grounded": True,
            "answer_leakage": False,
        },
    }


def test_unique_sequence_and_single_active_round(interview_db):
    session = _session("preparing_question")
    first = InterviewSessionRepository.create_round(session, _snapshot())
    with pytest.raises(DomainError, match="active round"):
        InterviewSessionRepository.create_round(session, _snapshot("q-2"))
    duplicate = _snapshot("q-duplicate")
    planner_action = duplicate.pop("planner_action")
    duplicate.update(
        target_requirement_id=planner_action["target_requirement_id"],
        selected_action=planner_action["selected_action"],
        selection_reason=planner_action["reason"],
        planner_actions=[planner_action],
    )
    with pytest.raises(IntegrityError):
        InterviewRound.create(
            id="round-duplicate",
            session_id=session.id,
            sequence=first.sequence,
            status="completed",
            active_guard=None,
            **duplicate,
            **_timestamps(),
        )


def test_optimistic_lock_accepts_at_most_one_stale_transition(interview_db):
    session = _session()
    stale = InterviewSession.get_by_id(session.id)
    changed = InterviewSessionRepository.transition(session, "preparing_question", expected_version=0)
    assert changed.state_version == 1
    with pytest.raises(DomainError) as error:
        InterviewSessionRepository.transition(stale, "preparing_question", expected_version=0)
    assert error.value.code == "state_conflict"


def test_idempotency_replays_same_payload_and_rejects_reuse(interview_db):
    session = _session()
    request, replay = InterviewRequestService.begin(session.id, "request-1", "answer", "hash-a")
    assert not replay
    InterviewRequestService.finish(request, {"events": [{"event": "answer_received", "data": {}}]})
    persisted, replay = InterviewRequestService.begin(session.id, "request-1", "answer", "hash-a")
    assert replay
    assert persisted.response["events"][0]["event"] == "answer_received"
    with pytest.raises(DomainError) as error:
        InterviewRequestService.begin(session.id, "request-1", "answer", "hash-b")
    assert error.value.code == "idempotency_conflict"


def test_abort_is_transactional_and_idempotent(interview_db):
    session = _session()
    application = InterviewApplication(_JudgeOnlyRuntime(), _E2ERunner())
    first = application.abort(session.id, "tenant-1", "user-1", 0, "abort-1")
    replay = application.abort(session.id, "tenant-1", "user-1", 0, "abort-1")
    assert first == replay
    assert replay["status"] == "aborted"
    assert InterviewRequest.select().where(InterviewRequest.session_id == session.id).count() == 1


def test_transaction_rollback_does_not_leave_partial_round(interview_db):
    session = _session("preparing_question")
    with pytest.raises(RuntimeError), interview_db.atomic():
        InterviewSessionRepository.create_round(session, _snapshot())
        raise RuntimeError("force rollback")
    assert InterviewRound.select().count() == 0


def test_tenant_and_user_scope_are_both_enforced(interview_db):
    session = _session()
    job = InterviewJob.create(
        id="job-scope",
        tenant_id="tenant-1",
        user_id="user-1",
        name="Scoped job",
        source_type="paste",
        source_text="Requires Go.",
        **_timestamps(),
    )
    assert InterviewSessionRepository.get(session.id, "tenant-1", "user-1").id == session.id
    assert InterviewJobService.get(job.id, "tenant-1", "user-1").id == job.id
    for tenant_id, user_id in (("tenant-2", "user-1"), ("tenant-1", "user-2")):
        with pytest.raises(DomainError) as error:
            InterviewSessionRepository.get(session.id, tenant_id, user_id)
        assert error.value.http_status == 404
        with pytest.raises(DomainError) as error:
            InterviewJobService.get(job.id, tenant_id, user_id)
        assert error.value.http_status == 404


def test_session_uses_immutable_job_resume_match_and_plan_snapshots(interview_db, monkeypatch):
    resume = InterviewResume.create(
        id="resume-snapshot",
        tenant_id="tenant-snapshot",
        user_id="user-snapshot",
        dataset_id="resume-dataset",
        document_id="resume-document",
        file_name="resume.md",
        extraction={
            "technology_stack": ["Go"],
            "claimed_skills": [{"skill": "Go", "claimed_level": "proficient", "topics": ["go.runtime"]}],
            "projects": [],
        },
        **_timestamps(),
    )
    job = InterviewJob.create(
        id="job-snapshot",
        tenant_id="tenant-snapshot",
        user_id="user-snapshot",
        name="Go role",
        source_type="paste",
        source_text="必须熟悉 Go 并理解并发",
        extraction={
            "requirements": [
                {
                    "requirement_id": "req-go",
                    "text": "必须熟悉 Go 并理解并发",
                    "category": "must_have",
                    "skills": ["Go"],
                    "topic_ids": ["go.runtime"],
                    "expected_level": "medium",
                    "weight": 1,
                    "evidence_span": "必须熟悉 Go 并理解并发",
                    "extraction_confidence": 1,
                    "unmapped": False,
                }
            ],
            "unmapped_requirement_ids": [],
        },
        **_timestamps(),
    )
    profile = InterviewProfile.create(
        id="profile-snapshot",
        tenant_id="tenant-snapshot",
        user_id="user-snapshot",
        name="snapshot profile",
        target_role="go_backend",
        target_level="mid",
        technology_stack=["Go"],
        focus_topics=[],
        excluded_topics=[],
        initial_difficulty="medium",
        preferred_categories=["baguwen"],
        question_count=3,
        max_followups=1,
        resume_id=resume.id,
        job_id=job.id,
        **_timestamps(),
    )
    config = InterviewKnowledgeConfig.create(
        id="config-snapshot",
        tenant_id="tenant-snapshot",
        user_id="user-snapshot",
        interview_experience_dataset_id="experience",
        leetcode_dataset_id="leetcode",
        fundamentals_dataset_id="fundamentals",
        retrieval_config_snapshot={"top_n": 3},
        metadata_quality_snapshot={},
        enabled=True,
        **_timestamps(),
    )
    monkeypatch.setattr(
        InterviewKnowledgeService,
        "revalidate",
        lambda _config: {
            field: {
                "version": "v1",
                "document_count": 1,
                "embedding_model": "embedding/test",
                "parsed": True,
            }
            for field in InterviewKnowledgeService.FIELDS
        },
    )
    session = InterviewSessionRepository.create(
        "tenant-snapshot",
        "user-snapshot",
        profile.id,
        config.id,
    )
    InterviewJob.update(source_text="changed", extraction={"requirements": []}).where(InterviewJob.id == job.id).execute()
    InterviewResume.update(extraction={"technology_stack": ["Rust"]}).where(InterviewResume.id == resume.id).execute()
    InterviewProfile.update(name="changed").where(InterviewProfile.id == profile.id).execute()
    restored = InterviewSession.get_by_id(session.id)
    assert restored.job_snapshot["source_text"] == "必须熟悉 Go 并理解并发"
    assert restored.resume_snapshot["technology_stack"] == ["Go"]
    assert restored.profile_snapshot["name"] == "snapshot profile"
    assert restored.match_snapshot[0]["verification_status"] == "untested"
    assert restored.initial_interview_plan == restored.current_interview_plan


def test_terminal_session_personal_data_can_be_anonymized(interview_db):
    session = _session("completed")
    InterviewSession.update(
        profile_snapshot={"name": "Alice"},
        resume_snapshot={"summary": "private resume"},
        job_snapshot={"source_text": "private JD"},
        current_candidate_state={"newly_claimed_facts": [{"fact": "private"}]},
    ).where(InterviewSession.id == session.id).execute()
    InterviewOperation.create(
        id="operation-private",
        tenant_id="tenant-1",
        user_id="user-1",
        session_id=session.id,
        request_id="request-private",
        operation_type="evaluate_answer",
        payload_hash="hash",
        payload={"answer": "private answer"},
        result_summary={"session": {"answer": "private answer"}},
        deadline_at="2026-08-08 12:05:00",
        **_timestamps(),
    )
    InterviewRequest.create(
        id="request-private",
        session_id=session.id,
        request_id="request-private",
        operation="answer",
        payload_hash="hash",
        response={"answer": "private answer"},
        operation_id="operation-private",
        **_timestamps(),
    )
    InterviewEvent.create(
        id="event-private",
        session_id=session.id,
        operation_id="operation-private",
        operation_sequence=1,
        sequence=1,
        event_type="feedback",
        public_payload={"feedback": "private answer"},
        **_timestamps(),
    )
    InterviewOperationCheckpoint.create(
        id="checkpoint-private",
        operation_id="operation-private",
        checkpoint_key="call-private",
        stage="judge",
        value={"output": "private prompt result"},
        **_timestamps(),
    )
    InterviewModelCall.create(
        id="model-private",
        tenant_id="tenant-1",
        session_id=session.id,
        operation_id="operation-private",
        stage="judge",
        prompt_snapshot={"user": "private answer"},
        **_timestamps(),
    )
    anonymized = InterviewSessionRepository.anonymize(session.id, "tenant-1", "user-1")
    assert anonymized.profile_snapshot == {"redacted": True}
    assert anonymized.resume_snapshot == {"redacted": True}
    assert anonymized.job_snapshot == {"redacted": True}
    assert InterviewEvent.select().where(InterviewEvent.session_id == session.id).count() == 0
    assert InterviewOperationCheckpoint.select().count() == 0
    assert InterviewOperation.get_by_id("operation-private").result_summary == {"redacted": True}
    assert InterviewRequest.get_by_id("request-private").response == {"redacted": True}
    assert InterviewModelCall.get_by_id("model-private").prompt_snapshot == {"redacted": True}


def test_referenced_resume_deletion_aborts_active_session_and_scrubs_operation_copies(interview_db, monkeypatch):
    resume = InterviewResume.create(
        id="resume-private",
        tenant_id="tenant-1",
        user_id="user-1",
        dataset_id="resume-dataset",
        document_id="resume-document",
        file_name="private-resume.pdf",
        extraction={
            "technology_stack": ["Go"],
            "claimed_skills": [{"skill": "Go", "claimed_level": "proficient", "topics": ["go.runtime"]}],
            "projects": [{"name": "private project", "summary": "private details"}],
        },
        **_timestamps(),
    )
    session = _session("awaiting_answer")
    InterviewProfile.update(resume_id=resume.id).where(InterviewProfile.id == session.profile_id).execute()
    InterviewSession.update(
        resume_snapshot=resume.extraction,
        current_candidate_state={"project_facts": [{"fact": "private project"}]},
    ).where(InterviewSession.id == session.id).execute()
    InterviewOperation.create(
        id="operation-resume-private",
        tenant_id="tenant-1",
        user_id="user-1",
        session_id=session.id,
        request_id="request-resume-private",
        operation_type="evaluate_answer",
        payload_hash="hash",
        payload={"answer": "private"},
        result_summary={"resume_probe": {"project": "private project"}},
        deadline_at="2026-08-08 12:05:00",
        **_timestamps(),
    )
    InterviewRequest.create(
        id="request-resume-private",
        session_id=session.id,
        request_id="request-resume-private",
        operation="answer",
        payload_hash="hash",
        response={"resume_probe": {"project": "private project"}},
        operation_id="operation-resume-private",
        **_timestamps(),
    )
    InterviewEvent.create(
        id="event-resume-private",
        session_id=session.id,
        operation_id="operation-resume-private",
        operation_sequence=1,
        sequence=1,
        event_type="next_question",
        public_payload={"round": {"resume_probe": {"project": "private project"}}},
        **_timestamps(),
    )
    InterviewOperationCheckpoint.create(
        id="checkpoint-resume-private",
        operation_id="operation-resume-private",
        checkpoint_key="resume-call",
        stage="generate_question",
        value={"output": "private project"},
        **_timestamps(),
    )
    InterviewModelCall.create(
        id="model-resume-private",
        tenant_id="tenant-1",
        session_id=session.id,
        operation_id="operation-resume-private",
        stage="generate_question",
        prompt_snapshot={"user": "private project"},
        **_timestamps(),
    )

    fake_file_service = types.ModuleType("api.db.services.file_service")
    fake_file_service.FileService = types.SimpleNamespace(delete_docs=lambda *_args, **_kwargs: "")
    monkeypatch.setitem(sys.modules, "api.db.services.file_service", fake_file_service)
    monkeypatch.setattr(
        resume_service,
        "Document",
        types.SimpleNamespace(id=object(), get_or_none=lambda *_args, **_kwargs: None),
    )

    resume_service.delete_resume("tenant-1", "user-1", resume)

    assert InterviewResume.get_or_none(InterviewResume.id == resume.id) is None
    restored_session = InterviewSession.get_by_id(session.id)
    assert restored_session.status == "aborted"
    assert restored_session.resume_snapshot["redacted"] is True
    assert "projects" not in restored_session.resume_snapshot
    assert restored_session.current_candidate_state["project_facts"] == []
    assert InterviewEvent.select().where(InterviewEvent.session_id == session.id).count() == 0
    assert InterviewOperationCheckpoint.select().where(
        InterviewOperationCheckpoint.operation_id == "operation-resume-private"
    ).count() == 0
    assert InterviewOperation.get_by_id("operation-resume-private").result_summary == {"redacted": True}
    assert InterviewModelCall.get_by_id("model-resume-private").prompt_snapshot == {"redacted": True}


def test_candidate_dto_drops_private_question_and_intermediate_judge_fields(interview_db):
    session = _session("preparing_question")
    round_ = InterviewSessionRepository.create_round(session, _snapshot())
    round_.candidate_answers = [
        {
            "kind": "initial",
            "answer": "candidate answer",
            "submitted_at": "now",
            "evaluation": {
                "score": 2,
                "verdict": "partial",
                "feedback": "safe feedback",
                "missing_points": ["private missing answer"],
            },
        }
    ]
    round_.save()
    payload = public_round(round_, include_evaluation=False)
    serialized = str(payload)
    assert "reference_answer" not in payload
    assert "evaluation_rubric" not in payload
    assert "retrieval_evidence" not in payload
    assert "planner_actions" not in payload
    assert "answer_state" not in payload
    assert "question_validation" not in payload
    assert "private original content" not in serialized
    assert "private missing answer" not in serialized
    assert public_session(session)["id"] == session.id
    assert "tenant_id" not in public_session(session)
    assert "user_id" not in public_session(session)


class _E2ERuntime:
    def __init__(self):
        self.judge_calls = 0

    async def retrieve(self, tenant_id, dataset_id, query, config):
        if dataset_id == "dataset-3" and "topic_id=go.runtime" in query:
            content_type, topic, question_id = "fundamentals", "go.runtime", "go-channel-001"
            content = "Sending to a closed Go channel panics. Receivers drain buffered values and then receive the zero value with ok=false. These are the verified closed-channel semantics."
        elif dataset_id == "dataset-2" and "topic_id=algorithm.core" in query:
            content_type, topic, question_id = "leetcode", "algorithm.core", "two-sum-001"
            content = (
                "Two-sum can be solved in O(n) using a hash map from value to index.\n"
                "## 标准解法\n- Check the complement before inserting and return the two matching indices.\n"
                "## 评分点\n- Use O(n) time and return correct indices."
            )
        else:
            return []
        return [
            {
                "evidence_id": f"chunk-{question_id}",
                "dataset_id": dataset_id,
                "document_id": f"doc-{question_id}",
                "document_name": "Original synthetic interview fixture",
                "content": content,
                "similarity": 0.95,
                "metadata": {
                    "content_type": content_type,
                    "role": "go_backend",
                    "topic": topic,
                    "difficulty": "medium",
                    "question_id": question_id,
                    "source": "synthetic",
                    "source_date": "2026-01-01",
                    "quality_score": 1.0,
                    "verified": True,
                    "license": "CC0",
                },
            }
        ]

    async def chat(self, tenant_id, system, user, *, temperature=0.1):
        if "grounded question generator" in system:
            if "algorithm.core" in user:
                return (
                    json.dumps(
                        {
                            "question_text": "Return the indices of two numbers whose sum equals the target value.",
                            "reference_answer": "Use a hash map from value to index, checking the complement before inserting in linear time.",
                            "evaluation_rubric": ["hash map", "linear time", "correct indices"],
                            "code_spec": {
                                "function_name": "solve",
                                "visible_tests": [{"input": [[2, 7, 11, 15], 9], "expected": [0, 1]}],
                                "hidden_tests": [{"input": [[3, 2, 4], 6], "expected": [1, 2]}],
                                "constraints": "One solution exists.",
                                "complexity_expectation": "O(n)",
                                "language": "python",
                                "reference_solution": "def solve(values, target):\n    seen = {}\n    for i, value in enumerate(values):\n        if target - value in seen:\n            return [seen[target - value], i]\n        seen[value] = i\n    return []",
                            },
                        }
                    ),
                    "fake-model-v1",
                )
            return (
                json.dumps(
                    {
                        "question_text": "What happens when a Go channel is closed for senders and receivers?",
                        "reference_answer": "A send to a closed channel panics; receives drain buffered values and then return the zero value with ok false.",
                        "evaluation_rubric": ["send panics", "buffer drains", "zero value and ok false"],
                    }
                ),
                "fake-model-v1",
            )
        if "technical interview judge" in system:
            self.judge_calls += 1
            if self.judge_calls == 1:
                result = {
                    "score": 2,
                    "verdict": "partial",
                    "covered_points": ["send panics"],
                    "missing_points": ["receive semantics"],
                    "factual_errors": [],
                    "needs_followup": True,
                    "followup_focus": "receive semantics after buffered values are drained",
                    "weak_point": "channel receive semantics",
                    "feedback": "The send side is correct; explain the receive side.",
                    "evaluation_summary": "Partial channel semantics.",
                    "confidence": 0.95,
                }
            else:
                result = {
                    "score": 4,
                    "verdict": "excellent",
                    "covered_points": ["all rubric points"],
                    "missing_points": [],
                    "factual_errors": [],
                    "needs_followup": False,
                    "followup_focus": "",
                    "weak_point": "",
                    "feedback": "Complete and correct.",
                    "evaluation_summary": "All evidence-backed points were covered.",
                    "confidence": 0.96,
                }
            return json.dumps(result), "fake-judge-v1"
        if "interview follow-up" in system:
            return json.dumps({"question": "What does a receiver observe after buffered values are drained?"}), "fake-model-v1"
        if "extract interview state" in system:
            return (
                json.dumps(
                    {
                        "technical_concepts": [],
                        "newly_claimed_facts": [],
                        "project_facts": [],
                        "contradictions": [],
                        "covered_rubric_points": [],
                        "unverified_boundaries": [],
                        "deep_dive_branches": [],
                    }
                ),
                "fake-state-v1",
            )
        raise AssertionError("Unexpected fake model prompt")

    async def embed(self, tenant_id, texts):
        return [[1.0, 0.0]] + [[0.0, 1.0] for _ in texts[1:]]

    def model_snapshot(self, tenant_id):
        return {"chat": {"model": "fake-model-v1"}, "embedding": {"model": "fake-embedding-v1"}}


class _E2ERunner:
    async def execute(self, language, source_code, tests):
        return {
            "status": "completed",
            "passed_count": len(tests),
            "total_count": len(tests),
            "runtime_ms": 7,
            "memory_kb": 1024,
            "compiler_output": "",
            "test_results": [
                {
                    "index": index,
                    "status": "passed",
                    "passed": True,
                    "actual": case["expected"],
                    "expected": case["expected"],
                    "runtime_ms": 7,
                }
                for index, case in enumerate(tests)
            ],
        }

    async def health(self):
        return True


class _FailingPreflightRunner:
    async def execute(self, _language, _source_code, tests):
        return {
            "status": "completed",
            "passed_count": len(tests) - 1,
            "total_count": len(tests),
        }


def test_coding_question_is_blocked_when_reference_solution_fails_a_hidden_test():
    snapshot = _snapshot("coding-preflight")
    snapshot.update(
        category="leetcode",
        question_type="coding",
        evaluation_rubric={
            "code_spec": {
                "language": "python",
                "reference_solution": "print(input())",
                "visible_tests": [{"input": "1", "expected": "1"}],
                "hidden_tests": [{"input": "2", "expected": "2"}],
            }
        },
    )
    application = InterviewApplication(runner=_FailingPreflightRunner())

    with pytest.raises(DomainError) as error:
        asyncio.run(application._preflight_question(snapshot))

    assert error.value.code == "code_question_preflight_failed"


async def _events(generator):
    return [event async for event in generator]


def test_fake_runtime_full_interview_e2e_with_refresh_code_and_report(interview_db):
    profile = InterviewProfile.create(
        id="profile-e2e",
        tenant_id="tenant-e2e",
        user_id="user-e2e",
        name="e2e",
        target_role="go_backend",
        target_level="mid",
        technology_stack=["Go"],
        focus_topics=["go.runtime"],
        excluded_topics=["database.mysql", "backend.distributed"],
        initial_difficulty="medium",
        preferred_categories=["baguwen", "leetcode"],
        question_count=2,
        max_followups=2,
        **_timestamps(),
    )
    config = InterviewKnowledgeConfig.create(
        id="config-e2e",
        tenant_id="tenant-e2e",
        user_id="user-e2e",
        interview_experience_dataset_id="dataset-1",
        leetcode_dataset_id="dataset-2",
        fundamentals_dataset_id="dataset-3",
        retrieval_config_snapshot={"top_n": 5},
        metadata_quality_snapshot={},
        enabled=True,
        **_timestamps(),
    )
    requirements = [
        {
            "requirement_id": "req-go",
            "text": "Understand Go channel semantics",
            "category": "must_have",
            "skills": ["Go"],
            "topic_ids": ["go.runtime"],
            "expected_level": "medium",
            "weight": 0.6,
            "evidence_span": "Understand Go channel semantics",
            "extraction_confidence": 1,
            "unmapped": False,
        },
        {
            "requirement_id": "req-algorithm",
            "text": "Implement core algorithms",
            "category": "must_have",
            "skills": ["algorithms"],
            "topic_ids": ["algorithm.core"],
            "expected_level": "medium",
            "weight": 0.4,
            "evidence_span": "Implement core algorithms",
            "extraction_confidence": 1,
            "unmapped": False,
        },
    ]
    plan = [
        {
            "requirement_id": "req-go",
            "topic_id": "go.runtime",
            "priority": 2,
            "objective": "Verify Go channel semantics",
            "preferred_question_type": "theory",
            "target_difficulty": "medium",
            "verification_strategy": "verify_resume_claim",
            "status": "pending",
            "attempt_count": 0,
        },
        {
            "requirement_id": "req-algorithm",
            "topic_id": "algorithm.core",
            "priority": 1,
            "objective": "Verify algorithm implementation",
            "preferred_question_type": "coding",
            "target_difficulty": "medium",
            "verification_strategy": "verify_jd_requirement",
            "status": "pending",
            "attempt_count": 0,
        },
    ]
    session = InterviewSession.create(
        id="session-e2e",
        tenant_id="tenant-e2e",
        user_id="user-e2e",
        profile_id=profile.id,
        knowledge_config_id=config.id,
        status="created",
        current_difficulty="medium",
        max_questions=2,
        max_followups=2,
        completed_question_count=0,
        current_round_sequence=0,
        state_version=0,
        model_config_snapshot={},
        knowledge_base_versions={},
        profile_snapshot={
            "target_role": "go_backend",
            "target_level": "mid",
            "technology_stack": ["Go"],
            "focus_topics": ["go.runtime"],
            "excluded_topics": ["database.mysql", "backend.distributed"],
            "preferred_categories": ["baguwen", "leetcode"],
            "initial_difficulty": "medium",
        },
        knowledge_config_snapshot={
            "interview_experience_dataset_id": "dataset-1",
            "leetcode_dataset_id": "dataset-2",
            "fundamentals_dataset_id": "dataset-3",
            "retrieval_config_snapshot": {"top_n": 5},
        },
        job_snapshot={
            "id": "job-e2e",
            "name": "Go backend",
            "extraction": {"requirements": requirements, "unmapped_requirement_ids": []},
        },
        resume_snapshot={
            "technology_stack": ["Go"],
            "claimed_skills": [{"skill": "Go", "claimed_level": "proficient", "topics": ["go.runtime"]}],
            "projects": [],
        },
        match_snapshot=[
            {
                "requirement_id": "req-go",
                "resume_evidence": [{"source": "resume_claim", "text": "Go"}],
                "match_status": "matched",
                "verification_status": "untested",
            },
            {
                "requirement_id": "req-algorithm",
                "resume_evidence": [],
                "match_status": "missing",
                "verification_status": "untested",
            },
        ],
        initial_interview_plan=plan,
        current_interview_plan=plan,
        current_candidate_state=initial_candidate_state(),
        planner_version="cs-interview-planner-v1",
        performance_snapshot={},
        **_timestamps(),
    )
    application = InterviewApplication(_E2ERuntime(), _E2ERunner())

    start = asyncio.run(_events(application.start_events(session.id, "tenant-e2e", "user-e2e", "start-1", 0)))
    assert [event["event"] for event in start] == ["next_question"]
    restored = public_session(InterviewSession.get_by_id(session.id))
    assert restored["active_round"]["question_id"] == "go-channel-001"
    assert restored["state_version"] == 2

    first = asyncio.run(
        _events(
            application.answer_events(
                session.id,
                "tenant-e2e",
                "user-e2e",
                "Sending panics.",
                "answer-1",
                restored["state_version"],
            )
        )
    )
    assert [event["event"] for event in first] == [
        "answer_received",
        "evaluating",
        "feedback",
        "followup_question",
    ]
    restored = public_session(InterviewSession.get_by_id(session.id))
    assert restored["active_round"]["followup_count"] == 1

    followup = asyncio.run(
        _events(
            application.answer_events(
                session.id,
                "tenant-e2e",
                "user-e2e",
                "It drains buffered values, then returns zero and ok=false.",
                "answer-2",
                restored["state_version"],
            )
        )
    )
    assert [event["event"] for event in followup][-1] == "next_question"
    restored = public_session(InterviewSession.get_by_id(session.id))
    assert restored["active_round"]["category"] == "leetcode"
    assert restored["rounds"][0]["initial_score"] == 2
    assert restored["rounds"][0]["score"] == 4

    code_result = asyncio.run(
        application.execute_code(
            session.id,
            "tenant-e2e",
            "user-e2e",
            "python",
            "import json\nprint(json.dumps([1, 2]))",
            hidden=True,
            request_id="code-1",
        )
    )
    assert code_result["hidden_test_summary"] == {"status": "completed", "passed_count": 1, "total_count": 1}
    assert "source_code" not in code_result
    assert "test_results" not in code_result["hidden_test_summary"]
    code_replay = asyncio.run(
        application.execute_code(
            session.id,
            "tenant-e2e",
            "user-e2e",
            "python",
            "import json\nprint(json.dumps([1, 2]))",
            hidden=True,
            request_id="code-1",
        )
    )
    assert code_replay == code_result
    assert CodeSubmission.select().where(CodeSubmission.session_id == session.id).count() == 1

    restored = public_session(InterviewSession.get_by_id(session.id))
    final = asyncio.run(
        _events(
            application.answer_events(
                session.id,
                "tenant-e2e",
                "user-e2e",
                "Use a complement hash map for O(n) time.",
                "answer-3",
                restored["state_version"],
            )
        )
    )
    assert [event["event"] for event in final][-1] == "interview_completed"
    completed = public_session(InterviewSession.get_by_id(session.id))
    assert completed["status"] == "completed"
    assert completed["completed_question_count"] == 2
    assert completed["current_difficulty"] == "advanced"
    assert completed["report"]["metrics"]["question_count"] == 2

    replay = asyncio.run(
        _events(
            application.answer_events(
                session.id,
                "tenant-e2e",
                "user-e2e",
                "Sending panics.",
                "answer-1",
                2,
            )
        )
    )
    assert replay == first


class _JudgeOnlyRuntime:
    async def retrieve(self, *_args, **_kwargs):
        raise AssertionError("No next question should be generated")

    async def chat(self, tenant_id, system, user, *, temperature=0.1):
        if "extract interview state" in system:
            return (
                json.dumps(
                    {
                        "technical_concepts": [],
                        "newly_claimed_facts": [],
                        "project_facts": [],
                        "contradictions": [],
                        "covered_rubric_points": [],
                        "unverified_boundaries": [],
                        "deep_dive_branches": [],
                    }
                ),
                "fake-state",
            )
        assert "technical interview judge" in system
        return (
            json.dumps(
                {
                    "score": 4,
                    "verdict": "excellent",
                    "covered_points": ["all"],
                    "missing_points": [],
                    "factual_errors": [],
                    "needs_followup": False,
                    "followup_focus": "",
                    "weak_point": "",
                    "feedback": "Complete.",
                    "evaluation_summary": "Complete.",
                    "confidence": 0.99,
                }
            ),
            "fake-judge",
        )

    async def embed(self, *_args, **_kwargs):
        return []

    def model_snapshot(self, _tenant_id):
        return {}


def test_concurrent_second_answer_is_rejected_without_failing_accepted_request(interview_db):
    session = _session("awaiting_answer")
    InterviewSession.update(max_questions=1, state_version=2).where(InterviewSession.id == session.id).execute()
    session = InterviewSession.get_by_id(session.id)
    round_ = InterviewSessionRepository.create_round(session, _snapshot())
    InterviewSessionRepository.transition_round(round_, "awaiting_answer")
    application = InterviewApplication(_JudgeOnlyRuntime(), _E2ERunner())

    async def scenario():
        accepted = application.answer_events(
            session.id,
            "tenant-1",
            "user-1",
            "accepted answer",
            "concurrent-1",
            2,
        )
        first_event = await anext(accepted)
        assert first_event["event"] == "answer_received"
        with pytest.raises(DomainError) as error:
            await _events(
                application.answer_events(
                    session.id,
                    "tenant-1",
                    "user-1",
                    "duplicate answer",
                    "concurrent-2",
                    2,
                )
            )
        assert error.value.code == "not_awaiting_answer"
        assert InterviewSession.get_by_id(session.id).status == "evaluating"
        rest = [event async for event in accepted]
        return rest

    events = asyncio.run(scenario())
    assert [event["event"] for event in events][-1] == "interview_completed"
    assert InterviewSession.get_by_id(session.id).status == "completed"
    assert InterviewRound.get_by_id(round_.id).candidate_answers[0]["answer"] == "accepted answer"
