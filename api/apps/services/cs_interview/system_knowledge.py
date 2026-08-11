"""Configuration boundary for the read-only platform interview corpus."""

from __future__ import annotations

import os
from dataclasses import dataclass

from api.apps.services.cs_interview.domain import DomainError

SYSTEM_DATASET_ENV = {
    "interview_experience_dataset_id": "CS_INTERVIEW_SYSTEM_INTERVIEW_EXPERIENCE_DATASET_ID",
    "leetcode_dataset_id": "CS_INTERVIEW_SYSTEM_LEETCODE_DATASET_ID",
    "fundamentals_dataset_id": "CS_INTERVIEW_SYSTEM_FUNDAMENTALS_DATASET_ID",
}


@dataclass(frozen=True)
class SystemKnowledgeConfig:
    tenant_id: str
    corpus_version: str
    dataset_ids: dict[str, str]

    def owner_for(self, field: str, dataset_id: str, default_tenant_id: str) -> str:
        return self.tenant_id if self.dataset_ids.get(field) == dataset_id else default_tenant_id


def load_system_knowledge_config(*, required: bool = False) -> SystemKnowledgeConfig | None:
    tenant_id = os.getenv("CS_INTERVIEW_SYSTEM_KNOWLEDGE_TENANT_ID", "").strip()
    dataset_ids = {field: os.getenv(env_name, "").strip() for field, env_name in SYSTEM_DATASET_ENV.items()}
    configured = [tenant_id, *dataset_ids.values()]
    if not any(configured):
        if required:
            raise DomainError(
                "system_knowledge_unconfigured",
                "The platform interview knowledge bases have not been configured.",
                http_status=503,
            )
        return None
    if not all(configured) or len(set(dataset_ids.values())) != len(dataset_ids):
        raise DomainError(
            "system_knowledge_invalid",
            "The platform interview knowledge base configuration is incomplete or duplicated.",
            http_status=503,
        )
    return SystemKnowledgeConfig(
        tenant_id=tenant_id,
        corpus_version=os.getenv("CS_INTERVIEW_SYSTEM_KNOWLEDGE_VERSION", "1").strip()[:32] or "1",
        dataset_ids=dataset_ids,
    )

