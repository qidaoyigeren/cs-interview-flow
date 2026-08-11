from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest
from peewee import SqliteDatabase

from api.apps.services.cs_interview.bootstrap_service import (
    InterviewKnowledgeBootstrapService,
    public_bootstrap,
)
from api.apps.services.cs_interview.competencies import ANCHOR_GROUPS
from api.apps.services.cs_interview.pipeline import RAGFlowRuntimeAdapter
from api.apps.services.cs_interview.system_knowledge import (
    SYSTEM_DATASET_ENV,
    load_system_knowledge_config,
)
from api.db.db_models import InterviewKnowledgeBootstrap, InterviewKnowledgeConfig, Knowledgebase
from api.db.services.interview_service import InterviewKnowledgeService


@pytest.fixture()
def bootstrap_db(tmp_path):
    database = SqliteDatabase(tmp_path / "bootstrap.sqlite")
    with database.bind_ctx([InterviewKnowledgeBootstrap], bind_refs=False, bind_backrefs=False):
        database.create_tables([InterviewKnowledgeBootstrap])
        try:
            yield database
        finally:
            database.drop_tables([InterviewKnowledgeBootstrap])
            database.close()


@pytest.fixture()
def system_quality_db(tmp_path):
    database = SqliteDatabase(tmp_path / "system-quality.sqlite")
    models = [InterviewKnowledgeConfig, Knowledgebase]
    with database.bind_ctx(models, bind_refs=False, bind_backrefs=False):
        database.create_tables(models)
        try:
            yield database
        finally:
            database.drop_tables(models)
            database.close()


@pytest.fixture()
def system_env(monkeypatch):
    values = {
        "interview_experience_dataset_id": "experience-kb",
        "leetcode_dataset_id": "leetcode-kb",
        "fundamentals_dataset_id": "fundamentals-kb",
    }
    monkeypatch.setenv("CS_INTERVIEW_SYSTEM_KNOWLEDGE_TENANT_ID", "system-tenant")
    monkeypatch.setenv("CS_INTERVIEW_SYSTEM_KNOWLEDGE_VERSION", "3")
    for field, env_name in SYSTEM_DATASET_ENV.items():
        monkeypatch.setenv(env_name, values[field])
    return values


@pytest.fixture()
def knowledge_service(monkeypatch):
    calls = []

    def save(tenant_id, user_id, payload):
        calls.append((tenant_id, user_id, payload))
        counts = {
            "interview_experience_dataset_id": 34,
            "leetcode_dataset_id": 33,
            "fundamentals_dataset_id": 33,
        }
        quality = {
            field: {
                "id": payload[field],
                "tenant_id": "system-tenant",
                "document_count": count,
                "chunk_count": count,
                "parsed": True,
            }
            for field, count in counts.items()
        }
        return SimpleNamespace(metadata_quality_snapshot=quality)

    monkeypatch.setattr(InterviewKnowledgeService, "latest", lambda *_args: None)
    monkeypatch.setattr(InterviewKnowledgeService, "save", save)
    return calls


def test_ensure_binds_preparsed_system_datasets_once(
    bootstrap_db,
    system_env,
    knowledge_service,
):
    created, existed = InterviewKnowledgeBootstrapService.ensure("tenant-1", "user-1")
    replayed, replay_existed = InterviewKnowledgeBootstrapService.ensure("tenant-1", "user-1")

    assert not existed
    assert replay_existed
    assert replayed.id == created.id
    assert created.status == "ready"
    assert created.dataset_ids == system_env
    assert sum(item["parsed"] for item in created.progress.values()) == 100
    assert len(knowledge_service) == 1
    assert public_bootstrap(created)["current_stage"] == "ready"


def test_system_dataset_owner_is_granted_only_for_exact_whitelisted_binding(system_env):
    config = load_system_knowledge_config(required=True)

    assert config.owner_for(
        "leetcode_dataset_id",
        system_env["leetcode_dataset_id"],
        "candidate-tenant",
    ) == "system-tenant"
    assert config.owner_for(
        "leetcode_dataset_id",
        "another-dataset",
        "candidate-tenant",
    ) == "candidate-tenant"


def test_exact_system_binding_reuses_the_validated_release_snapshot(
    system_quality_db,
    system_env,
    monkeypatch,
):
    quality = {}
    for index, (field, dataset_id) in enumerate(system_env.items(), start=1):
        dataset = Knowledgebase.create(
            id=dataset_id,
            tenant_id="system-tenant",
            name=field,
            embd_id="embedding-model",
            created_by="system-user",
            status="1",
            create_time=index,
            update_time=index,
        )
        dataset = Knowledgebase.get_by_id(dataset.id)
        quality[field] = {
            "id": dataset_id,
            "tenant_id": "system-tenant",
            "parsed": True,
            "version": str(dataset.update_time or dataset.create_time or ""),
            "embedding_model": "embedding-model",
            "metadata_quality": {"ready": True},
            "anchor_group_ids": list(ANCHOR_GROUPS) if index == 1 else [],
        }
    InterviewKnowledgeConfig.create(
        id="system-config",
        tenant_id="system-tenant",
        user_id="system-user",
        **system_env,
        metadata_quality_snapshot=quality,
        retrieval_config_snapshot={},
        enabled=True,
        create_time=1,
        update_time=1,
    )
    released = InterviewKnowledgeConfig.get_by_id("system-config").metadata_quality_snapshot
    for field, dataset_id in system_env.items():
        dataset = Knowledgebase.get_by_id(dataset_id)
        summary = released[field]
        assert summary["tenant_id"] == dataset.tenant_id
        assert summary["version"] == str(dataset.update_time or dataset.create_time or "")
        assert summary["metadata_quality"]["ready"] is True
    monkeypatch.setattr(
        InterviewKnowledgeService,
        "validate_bindings",
        lambda *_args: pytest.fail("system datasets must not be rescanned"),
    )

    snapshot = InterviewKnowledgeService._system_quality_snapshot("candidate-tenant", system_env)

    assert snapshot["leetcode_dataset_id"]["read_only"] is True
    assert {summary["tenant_id"] for summary in snapshot.values()} == {"system-tenant"}


def test_unconfigured_platform_corpus_fails_without_starting_document_ingestion(
    bootstrap_db,
    monkeypatch,
):
    monkeypatch.delenv("CS_INTERVIEW_SYSTEM_KNOWLEDGE_TENANT_ID", raising=False)
    for env_name in SYSTEM_DATASET_ENV.values():
        monkeypatch.delenv(env_name, raising=False)

    row, _ = InterviewKnowledgeBootstrapService.ensure("tenant-1", "user-1")

    assert row.status == "failed"
    assert row.error_code == "system_knowledge_unconfigured"
    assert row.progress == {}


def test_failed_binding_retries_in_place(
    bootstrap_db,
    system_env,
    knowledge_service,
):
    created, _ = InterviewKnowledgeBootstrapService.ensure("tenant-1", "user-1")
    InterviewKnowledgeBootstrap.update(
        status="failed",
        current_stage="failed",
        error_code="system_knowledge_binding_failed",
        error_message="temporary failure",
    ).where(InterviewKnowledgeBootstrap.id == created.id).execute()

    retried = InterviewKnowledgeBootstrapService.retry("tenant-1", "user-1")

    assert retried.id == created.id
    assert retried.status == "ready"
    assert retried.error_code is None
    assert InterviewKnowledgeBootstrap.select().count() == 1


@pytest.mark.asyncio
async def test_retrieval_uses_the_whitelisted_dataset_owner(monkeypatch):
    calls = []

    async def search(dataset_id, tenant_id, request):
        calls.append((dataset_id, tenant_id, request))
        return True, {"chunks": []}

    dataset_module = ModuleType("api.apps.services.dataset_api_service")
    dataset_module.search = search
    metadata_module = ModuleType("api.db.services.doc_metadata_service")
    metadata_module.DocMetadataService = SimpleNamespace(
        get_metadata_for_documents=lambda *_args: {},
    )
    monkeypatch.setitem(sys.modules, "api.apps.services.dataset_api_service", dataset_module)
    monkeypatch.setitem(sys.modules, "api.db.services.doc_metadata_service", metadata_module)

    result = await RAGFlowRuntimeAdapter().retrieve(
        "candidate-tenant",
        "system-kb",
        "go scheduler",
        {"dataset_tenant_ids": {"system-kb": "system-tenant"}},
    )

    assert result == []
    assert calls[0][0:2] == ("system-kb", "system-tenant")
