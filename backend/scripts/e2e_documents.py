"""端到端驱动（真实上游全链，需已配置凭据且中间件就绪）。

在**进程内**读取 Settings（含凭据），经真实 HTTP API 驱动：
login → 建 KB → 上传 PDF → 轮询文档状态直到 READY/FAILED。
不打印任何凭据；API 调用会真实调用 MinerU 解析 + DashScope 向量化，
并写入真实 MySQL / Milvus。需后端（:8000）与 Celery worker 已启动。

运行：`uv run python scripts/e2e_documents.py`
"""

from __future__ import annotations

import logging
import time

import httpx

from app.core.config import get_settings

logging.basicConfig(level=logging.INFO)

BASE = "http://127.0.0.1:8000/api/v1"


def make_pdf() -> bytes:
    """用 fpdf2 生成一个合法的一页 PDF（MinerU 可解析），含中文与英文文本。"""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Enterprise Knowledge Base RAG", ln=True)
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 12)
    body = (
        "This document is uploaded to exercise the full ingest chain. "
        "It covers onboarding, travel reimbursement, and expense policy. "
        "Employees must submit claims within 90 days of expense date."
    )
    pdf.multi_cell(0, 8, body)
    return bytes(pdf.output())


def main() -> None:
    s = get_settings()
    client = httpx.Client(base_url=BASE, timeout=120)

    # ---- login（进程内读密码，不打印）----
    resp = client.post(
        "/auth/login",
        json={
            "username": s.bootstrap_admin_username or "admin",
            "password": s.bootstrap_admin_password or "",
        },
    )
    resp.raise_for_status()
    access = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}
    print("LOGIN ok")

    # ---- 建 KB（唯一名，避免上次运行残留导致 409 同名冲突）----
    kb_name = f"E2E 链路验证库-{time.strftime('%H%M%S')}"
    resp = client.post(
        "/knowledge-bases",
        headers=headers,
        json={
            "name": kb_name,
            "description": "跑通上传→READY",
            "embedding_model": s.dashscope_embed_model,
            "embed_dim": s.dashscope_embed_dim,
        },
    )
    resp.raise_for_status()
    kb_id = resp.json()["id"]
    print(f"KB created id={kb_id}")

    # ---- 上传 PDF ----
    pdf = make_pdf()
    resp = client.post(
        f"/knowledge-bases/{kb_id}/documents",
        headers=headers,
        files={"file": ("e2e.pdf", pdf, "application/pdf")},
    )
    resp.raise_for_status()
    doc_id = resp.json()["id"]
    print(f"uploaded doc_id={doc_id} status={resp.json()['status']}")

    # ---- 轮询到终态 ----
    deadline = time.time() + 600
    while time.time() < deadline:
        resp = client.get(
            f"/knowledge-bases/{kb_id}/documents/{doc_id}", headers=headers
        )
        resp.raise_for_status()
        body = resp.json()
        status = body["status"]
        job = body.get("job_status")
        job_stage = body.get("job_stage")
        job_error = body.get("error_message")
        print(
            f"  poll status={status} job={job} stage={job_stage} "
            f"err={job_error!r}"
        )
        if status in ("READY", "FAILED"):
            print(f"FINAL status={status} job={job}")
            print(f"RESULT kb_id={kb_id} doc_id={doc_id}")
            return
        time.sleep(2)
    print("TIMEOUT waiting for terminal status")


if __name__ == "__main__":
    main()
