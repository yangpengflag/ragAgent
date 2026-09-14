"""文件存储抽象与本地实现。

`project.md`：本地文件系统为默认实现，`FileStorage` 接口可切 MinIO；
原始文件与解析产物均落盘。路径布局 `<root>/<kb_id>/<document_id>/`
（design D4）。对外只暴露**相对路径**（相对存储根），绝对根属配置，
业务层不拼根——便于日后迁移对象存储不改调用方。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class FileStorage(ABC):
    """文件存储抽象（原始文件 + 解析产物）。所有方法返回相对路径。"""

    @abstractmethod
    def save_raw(
        self, *, kb_id: str, document_id: str, filename: str, data: bytes
    ) -> str: ...

    @abstractmethod
    def open_raw(self, rel_path: str) -> bytes: ...

    @abstractmethod
    def save_artifact(
        self, *, kb_id: str, document_id: str, name: str, data: bytes
    ) -> str: ...

    @abstractmethod
    def open_artifact(self, rel_path: str) -> bytes: ...


class LocalFileStorage(FileStorage):
    """基于本地文件系统的实现。目录：`<root>/<kb_id>/<document_id>/`。"""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def _doc_dir(self, kb_id: str, document_id: str) -> Path:
        return self._root / kb_id / document_id

    def _resolve(self, rel_path: str) -> Path:
        path = (self._root / rel_path).resolve()
        root = self._root.resolve()
        # 防目录穿越：相对路径必须落在根内
        if not path.is_relative_to(root):
            raise ValueError(f"非法相对路径: {rel_path}")
        return path

    @staticmethod
    def _suffix(filename: str) -> str:
        suffix = Path(filename).suffix.lstrip(".")
        return suffix or "bin"

    def save_raw(
        self, *, kb_id: str, document_id: str, filename: str, data: bytes
    ) -> str:
        rel = f"{kb_id}/{document_id}/raw.{self._suffix(filename)}"
        return self._write(rel, data)

    def save_artifact(
        self, *, kb_id: str, document_id: str, name: str, data: bytes
    ) -> str:
        rel = f"{kb_id}/{document_id}/{name}"
        return self._write(rel, data)

    def _write(self, rel: str, data: bytes) -> str:
        path = self._resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return rel

    def open_raw(self, rel_path: str) -> bytes:
        return self._resolve(rel_path).read_bytes()

    def open_artifact(self, rel_path: str) -> bytes:
        return self._resolve(rel_path).read_bytes()