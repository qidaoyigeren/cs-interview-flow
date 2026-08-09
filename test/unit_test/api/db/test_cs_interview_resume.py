from types import SimpleNamespace

from api.apps.services.cs_interview import resume_service
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.user_service import TenantService


class _Query:
    def where(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def first(self):
        return None


class _Field:
    def __eq__(self, _other):
        return True

    def __lshift__(self, _other):
        return True

    def startswith(self, _other):
        return True

    def desc(self):
        return self


class _Knowledgebase:
    tenant_id = _Field()
    name = _Field()
    status = _Field()
    update_time = _Field()
    saved = SimpleNamespace(id="resume-kb", name="CS面试-简历库")

    @classmethod
    def select(cls):
        return _Query()

    @classmethod
    def get_or_none(cls, *_args):
        return cls.saved


def test_resume_dataset_creation_does_not_nest_service_connection_contexts(monkeypatch):
    monkeypatch.setattr(resume_service, "Knowledgebase", _Knowledgebase)
    monkeypatch.setattr(
        KnowledgebaseService,
        "create_with_name",
        lambda **_kwargs: (True, {"id": "resume-kb", "name": "CS面试-简历库", "embd_id": ""}),
    )
    monkeypatch.setattr(KnowledgebaseService, "save", lambda **_kwargs: True)
    monkeypatch.setattr(
        TenantService,
        "get_by_id",
        lambda _tenant_id: (True, SimpleNamespace(embd_id="embedding-test")),
    )

    class _NoOuterTransaction:
        def atomic(self):
            raise AssertionError("service-owned connection contexts must not be nested in DB.atomic")

    monkeypatch.setattr(resume_service, "DB", _NoOuterTransaction())

    result = resume_service.ensure_resume_dataset("tenant-1")

    assert result.id == "resume-kb"
