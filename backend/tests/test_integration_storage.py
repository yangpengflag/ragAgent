"""FileStorage 本地实现红灯（document-upload-and-parse 任务 2.1）。

验证目录布局 `<root>/<kb_id>/<document_id>/`、往返字节一致、产物独立路径。
"""

from __future__ import annotations

from pathlib import Path

from app.integrations.storage import LocalFileStorage


def test_save_and_open_raw_roundtrip(tmp_path: Path):
    storage = LocalFileStorage(root=tmp_path)
    kb_id, doc_id = "kb-1", "doc-1"

    rel = storage.save_raw(
        kb_id=kb_id, document_id=doc_id, filename="政策.pdf", data=b"%PDF-1.4 fake"
    )

    assert rel == "kb-1/doc-1/raw.pdf"
    assert (tmp_path / rel).exists()
    assert storage.open_raw(rel) == b"%PDF-1.4 fake"


def test_save_artifact_uses_separate_name(tmp_path: Path):
    storage = LocalFileStorage(root=tmp_path)
    kb_id, doc_id = "kb-1", "doc-1"

    rel = storage.save_artifact(
        kb_id=kb_id, document_id=doc_id, name="content_list.json", data=b'{"blocks":[]}'
    )

    assert rel == "kb-1/doc-1/content_list.json"
    assert storage.open_artifact(rel) == b'{"blocks":[]}'


def test_directories_isolated_by_kb_and_doc(tmp_path: Path):
    storage = LocalFileStorage(root=tmp_path)
    a = storage.save_raw(kb_id="kb-1", document_id="doc-1", filename="a.pdf", data=b"x")
    b = storage.save_raw(kb_id="kb-1", document_id="doc-2", filename="b.pdf", data=b"y")

    assert Path(a).parent != Path(b).parent


def test_raw_and_artifact_namespace(tmp_path: Path):
    """原始文件与解析产物落在同一文档目录但文件名不同。"""
    storage = LocalFileStorage(root=tmp_path)
    raw = storage.save_raw(kb_id="kb", document_id="doc", filename="f.pdf", data=b"x")
    art = storage.save_artifact(
        kb_id="kb", document_id="doc", name="content_list.json", data=b"y"
    )

    assert raw != art
    assert Path(raw).parent == Path(art).parent