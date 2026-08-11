"""Offline schema/index smoke test for the CS interview production tables."""

from __future__ import annotations

from peewee import IntegrityError, SqliteDatabase

from api.db.db_models import (
    CodeSubmission,
    InterviewAnnotationCase,
    InterviewAnnotationReview,
    InterviewAuditLog,
    InterviewDeletionRequest,
    InterviewEvaluationMetric,
    InterviewEvaluationRun,
    InterviewEvent,
    InterviewExperiment,
    InterviewExperimentAssignment,
    InterviewFeedback,
    InterviewKnowledgeBootstrap,
    InterviewModelCall,
    InterviewOperation,
    InterviewOperationCheckpoint,
    InterviewPricingVersion,
    InterviewRequest,
    InterviewReviewAction,
    InterviewRubricCalibration,
    InterviewTraceEvent,
)

MODELS = (
    InterviewOperation,
    InterviewRequest,
    InterviewEvent,
    InterviewOperationCheckpoint,
    InterviewModelCall,
    InterviewDeletionRequest,
    InterviewAuditLog,
    CodeSubmission,
    InterviewTraceEvent,
    InterviewEvaluationRun,
    InterviewEvaluationMetric,
    InterviewExperiment,
    InterviewExperimentAssignment,
    InterviewFeedback,
    InterviewKnowledgeBootstrap,
    InterviewReviewAction,
    InterviewPricingVersion,
    InterviewAnnotationCase,
    InterviewAnnotationReview,
    InterviewRubricCalibration,
)


def test_beta_tables_and_idempotency_indexes_create_on_existing_database(tmp_path):
    database = SqliteDatabase(tmp_path / "migration-smoke.sqlite")
    with database.bind_ctx(MODELS, bind_refs=False, bind_backrefs=False):
        # Safe creation twice models the owning init_database_tables rollout:
        # an existing database is preserved and missing Beta tables are added.
        database.create_tables(MODELS, safe=True)
        database.create_tables(MODELS, safe=True)

        operation_indexes = {tuple(index.columns): index.unique for index in database.get_indexes("interview_operation")}
        event_indexes = {tuple(index.columns): index.unique for index in database.get_indexes("interview_event")}
        checkpoint_indexes = {
            tuple(index.columns): index.unique for index in database.get_indexes("interview_operation_checkpoint")
        }

        assert operation_indexes[("session_id", "request_id")] is True
        assert event_indexes[("session_id", "sequence")] is True
        assert event_indexes[("operation_id", "operation_sequence")] is True
        assert checkpoint_indexes[("operation_id", "checkpoint_key")] is True
        assert any(index.unique and tuple(index.columns) == ("operation_id",) for index in database.get_indexes("interview_request"))
        assert any(index.unique and tuple(index.columns) == ("operation_id",) for index in database.get_indexes("code_submission"))

        trace_indexes = {tuple(index.columns) for index in database.get_indexes("interview_trace_event")}
        assert ("session_id", "occurred_at") in trace_indexes
        assert ("trace_id", "occurred_at") in trace_indexes
        assert ("tenant_id", "occurred_at") in trace_indexes
        assert ("event_type", "occurred_at") in trace_indexes
        assert ("round_id", "occurred_at") in trace_indexes

        evaluation_indexes = {tuple(index.columns) for index in database.get_indexes("interview_evaluation_metric")}
        assert ("run_id", "metric") in evaluation_indexes

        assignment_indexes = {tuple(index.columns): index.unique for index in database.get_indexes("interview_experiment_assignment")}
        assert assignment_indexes[("session_id",)] is True
        assert assignment_indexes[("experiment_id", "session_id")] is True
        feedback_indexes = {tuple(index.columns) for index in database.get_indexes("interview_feedback")}
        assert ("tenant_id", "create_time") in feedback_indexes

        annotation_review_indexes = {tuple(index.columns): index.unique for index in database.get_indexes("interview_annotation_review")}
        assert annotation_review_indexes[("case_id", "reviewer_id_hash")] is True
        annotation_case_indexes = {tuple(index.columns) for index in database.get_indexes("interview_annotation_case")}
        assert ("case_id",) in annotation_case_indexes
        calibration_indexes = {tuple(index.columns) for index in database.get_indexes("interview_rubric_calibration")}
        assert ("rubric_version", "competency_id", "metric") in calibration_indexes
        bootstrap_indexes = {
            tuple(index.columns): index.unique
            for index in database.get_indexes("interview_knowledge_bootstrap")
        }
        assert bootstrap_indexes[("tenant_id", "corpus_version")] is True

        common = {
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "session_id": "session-1",
            "request_id": "request-1",
            "operation_type": "start_interview",
            "payload_hash": "hash",
            "deadline_at": "2026-08-08 12:05:00",
        }
        InterviewOperation.create(id="operation-1", **common)
        try:
            InterviewOperation.create(id="operation-2", **common)
        except IntegrityError:
            pass
        else:  # pragma: no cover - demonstrates the required production guard
            raise AssertionError("duplicate (session_id, request_id) was accepted")

    database.close()
