"""文档列表/详情/软删路由红灯（document-upload-and-parse 任务 5.3）。

覆盖列表/详情/软删接口的状态码、权限（可访问 vs 管理）与响应形状。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_document_routes import PDF, _DocFixture

from app.core.ids import uuid7
from app.integrations.storage import LocalFileStorage
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.user import SystemRole
from app.models.user_kb_grant import KbRole, UserKbGrant
from app.services import kb_service


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(root=tmp_path)


def _grant(session: Session, kb: KnowledgeBase, username: str, role: KbRole):
    from test_kb_routes import _user

    user = _user(session, username, SystemRole.MEMBER)
    session.add(UserKbGrant(user_id=user.id, kb_id=kb.id, role=role))
    session.commit()
    return user


def _uploaded(session: Session, client, kb_id) -> str:
    return client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents",
        files={"file": ("a.pdf", PDF, "application/pdf")},
    ).json()["id"]


def test_list_returns_items_only_active(sqlite_session: Session, storage: LocalFileStorage):
    from test_kb_routes import _kb, _user

    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _DocFixture(sqlite_session, admin, storage).client
    _uploaded(sqlite_session, client, kb.id)
    other = kb_service.create_kb(
        sqlite_session, name="另一库", embedding_model="m", embed_dim=128
    )
    _uploaded(sqlite_session, client, other.id)

    body = client.get(f"/api/v1/knowledge-bases/{kb.id}/documents").json()

    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["filename"] == "a.pdf"
    assert item["status"] == "UPLOADED"
    assert item["job_status"] == "PENDING"
    assert body["request_id"]


def test_list_excludes_soft_deleted(sqlite_session: Session, storage: LocalFileStorage):
    from test_kb_routes import _kb, _user

    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _DocFixture(sqlite_session, admin, storage).client
    doc_id = _uploaded(sqlite_session, client, kb.id)
    client.delete(f"/api/v1/knowledge-bases/{kb.id}/documents/{doc_id}")

    assert client.get(f"/api/v1/knowledge-bases/{kb.id}/documents").json()["items"] == []


def test_viewer_can_list(sqlite_session: Session, storage: LocalFileStorage):
    from test_kb_routes import _kb

    kb = _kb(sqlite_session)
    viewer = _grant(sqlite_session, kb, "viewer", KbRole.VIEWER)
    client = _DocFixture(sqlite_session, viewer, storage).client

    assert client.get(f"/api/v1/knowledge-bases/{kb.id}/documents").status_code == 200


def test_get_document_returns_detail(sqlite_session: Session, storage: LocalFileStorage):
    from test_kb_routes import _kb, _user

    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _DocFixture(sqlite_session, admin, storage).client
    doc_id = _uploaded(sqlite_session, client, kb.id)

    response = client.get(f"/api/v1/knowledge-bases/{kb.id}/documents/{doc_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == doc_id
    assert body["status"] == "UPLOADED"
    assert body["kb_id"] == str(kb.id)


def test_get_document_missing_returns_404(sqlite_session: Session, storage: LocalFileStorage):
    from test_kb_routes import _kb, _user

    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _DocFixture(sqlite_session, admin, storage).client

    response = client.get(f"/api/v1/knowledge-bases/{kb.id}/documents/{uuid7()}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_delete_soft_deletes(sqlite_session: Session, storage: LocalFileStorage):
    from test_kb_routes import _kb, _user

    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _DocFixture(sqlite_session, admin, storage).client
    doc_id = _uploaded(sqlite_session, client, kb.id)

    response = client.delete(f"/api/v1/knowledge-bases/{kb.id}/documents/{doc_id}")

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    doc = sqlite_session.scalar(
        select(Document)
        .where(Document.id == uuid.UUID(doc_id))
        .execution_options(include_soft_deleted=True)
    )
    assert doc is not None
    assert doc.deleted_at is not None
    assert client.get(f"/api/v1/knowledge-bases/{kb.id}/documents").json()["items"] == []


def test_delete_triggers_vector_cleanup(
    sqlite_session: Session, storage: LocalFileStorage, monkeypatch
):
    """document-embedding-index 任务 3.4：软删提交后尽力清理 Milvus 向量。"""
    from test_kb_routes import _kb, _user

    import app.integrations.milvus as milvus_integration

    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _DocFixture(sqlite_session, admin, storage).client
    doc_id = _uploaded(sqlite_session, client, kb.id)
    cleared: dict[str, str] = {}

    def fake_delete(settings, kb_id, document_id) -> None:  # noqa: ARG001
        cleared["kb_id"] = kb_id
        cleared["document_id"] = document_id

    monkeypatch.setattr(milvus_integration, "delete_document_vectors", fake_delete)

    resp = client.delete(f"/api/v1/knowledge-bases/{kb.id}/documents/{doc_id}")

    assert resp.status_code == 200
    assert cleared.get("kb_id") == str(kb.id)
    assert cleared.get("document_id") == doc_id


def test_viewer_cannot_soft_delete(sqlite_session: Session, storage: LocalFileStorage):
    """读写权限区分：VIEWER 可看但不可删。"""
    from test_kb_routes import _kb, _user

    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    admin_client = _DocFixture(sqlite_session, admin, storage).client
    doc_id = _uploaded(sqlite_session, admin_client, kb.id)
    viewer = _grant(sqlite_session, kb, "viewer2", KbRole.VIEWER)
    viewer_client = _DocFixture(sqlite_session, viewer, storage).client

    response = viewer_client.delete(
        f"/api/v1/knowledge-bases/{kb.id}/documents/{doc_id}"
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "access_denied"


def test_editor_can_soft_delete(sqlite_session: Session, storage: LocalFileStorage):
    from test_kb_routes import _kb

    kb = _kb(sqlite_session)
    editor = _grant(sqlite_session, kb, "editor", KbRole.EDITOR)
    client = _DocFixture(sqlite_session, editor, storage).client
    # 用 admin 建文档，editor 软删
    from test_kb_routes import _user

    admin_client = _DocFixture(
        sqlite_session, _user(sqlite_session, "root", SystemRole.ADMIN), storage
    ).client
    doc_id = _uploaded(sqlite_session, admin_client, kb.id)

    response = client.delete(f"/api/v1/knowledge-bases/{kb.id}/documents/{doc_id}")

    assert response.status_code == 200