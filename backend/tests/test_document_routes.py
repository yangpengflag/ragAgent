"""文档上传路由红灯（document-upload-and-parse 任务 5.1）。

覆盖上传 multipart 的成功/415/413/409/403/404 状态码与响应信封；
`require_kb_role`（`EDITOR`/`KB_ADMIN`）接线。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_kb_routes import _Fixture, _kb, _user

from app.api.deps import get_document_storage, get_upload_limits
from app.core.ids import uuid7
from app.integrations.storage import LocalFileStorage
from app.models.document import Document, DocumentStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.user import Account, SystemRole
from app.models.user_kb_grant import KbRole, UserKbGrant

PDF = b"%PDF-1.4 fake"


class _DocFixture(_Fixture):
    """增强：注入临时存储与可调上传限额（替代真实磁盘/配置）。"""

    def __init__(
        self,
        session: Session,
        account: Account | None,
        storage: LocalFileStorage,
        limits: tuple[int, frozenset[str]] = (1024, frozenset({"pdf", "docx"})),
    ) -> None:
        super().__init__(session, account)
        self.app.dependency_overrides[get_document_storage] = lambda: storage
        self.app.dependency_overrides[get_upload_limits] = lambda: limits

    def upload(self, kb_id, *, filename="政策.pdf", content=PDF, content_type="application/pdf"):
        return self.client.post(
            f"/api/v1/knowledge-bases/{kb_id}/documents",
            files={"file": (filename, content, content_type)},
        )


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(root=tmp_path)


def _editor(session: Session, kb: KnowledgeBase, username="ed") -> Account:
    user = _user(session, username, SystemRole.MEMBER)
    session.add(UserKbGrant(user_id=user.id, kb_id=kb.id, role=KbRole.EDITOR))
    session.commit()
    return user


def test_upload_success_returns_201(sqlite_session: Session, storage: LocalFileStorage):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _DocFixture(sqlite_session, admin, storage).client

    response = client.post(
        f"/api/v1/knowledge-bases/{kb.id}/documents",
        files={"file": ("政策.pdf", PDF, "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["kb_id"] == str(kb.id)
    assert body["filename"] == "政策.pdf"
    assert body["status"] == "UPLOADED"
    assert body["job_status"] == "PENDING"
    assert body["request_id"]


def test_upload_persists_raw_file(
    sqlite_session: Session, storage: LocalFileStorage, tmp_path: Path
):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _DocFixture(sqlite_session, admin, storage).client

    doc_id = client.post(
        f"/api/v1/knowledge-bases/{kb.id}/documents",
        files={"file": ("a.pdf", PDF, "application/pdf")},
    ).json()["id"]

    doc = sqlite_session.get(Document, uuid.UUID(doc_id))
    assert doc is not None
    assert doc.raw_path is not None
    assert storage.open_raw(doc.raw_path) == PDF


def test_editor_can_upload(sqlite_session: Session, storage: LocalFileStorage):
    kb = _kb(sqlite_session)
    editor = _editor(sqlite_session, kb)
    client = _DocFixture(sqlite_session, editor, storage).client

    assert client.post(
        f"/api/v1/knowledge-bases/{kb.id}/documents",
        files={"file": ("b.pdf", PDF, "application/pdf")},
    ).status_code == 201


def test_viewer_cannot_upload(sqlite_session: Session, storage: LocalFileStorage):
    kb = _kb(sqlite_session)
    viewer = _user(sqlite_session, "viewer", SystemRole.MEMBER)
    sqlite_session.add(UserKbGrant(user_id=viewer.id, kb_id=kb.id, role=KbRole.VIEWER))
    sqlite_session.commit()
    client = _DocFixture(sqlite_session, viewer, storage).client

    response = client.post(
        f"/api/v1/knowledge-bases/{kb.id}/documents",
        files={"file": ("b.pdf", PDF, "application/pdf")},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "access_denied"


def test_upload_unsupported_type_returns_415(
    sqlite_session: Session, storage: LocalFileStorage
):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _DocFixture(sqlite_session, admin, storage).client

    response = client.post(
        f"/api/v1/knowledge-bases/{kb.id}/documents",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json()["error_code"] == "unsupported_file_type"


def test_upload_too_large_returns_413(sqlite_session: Session, storage: LocalFileStorage):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _DocFixture(sqlite_session, admin, storage, limits=(4, frozenset({"pdf"}))).client

    response = client.post(
        f"/api/v1/knowledge-bases/{kb.id}/documents",
        files={"file": ("big.pdf", b"0123456789", "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["error_code"] == "file_too_large"


def test_upload_duplicate_conflicts(sqlite_session: Session, storage: LocalFileStorage):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _DocFixture(sqlite_session, admin, storage).client
    client.post(
        f"/api/v1/knowledge-bases/{kb.id}/documents",
        files={"file": ("a.pdf", PDF, "application/pdf")},
    )
    # 解析成功后再次上传同内容 → 409
    doc = sqlite_session.scalar(select(Document))
    doc.status = DocumentStatus.PARSED
    sqlite_session.commit()

    response = client.post(
        f"/api/v1/knowledge-bases/{kb.id}/documents",
        files={"file": ("a2.pdf", PDF, "application/pdf")},
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "conflict"


def test_upload_missing_kb_returns_404(sqlite_session: Session, storage: LocalFileStorage):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    client = _DocFixture(sqlite_session, admin, storage).client

    response = client.post(
        f"/api/v1/knowledge-bases/{uuid7()}/documents",
        files={"file": ("a.pdf", PDF, "application/pdf")},
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"