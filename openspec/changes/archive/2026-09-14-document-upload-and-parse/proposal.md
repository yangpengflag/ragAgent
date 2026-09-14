# Proposal: document-upload-and-parse

## Why

`rag-orchestration` 把检索格式（`RetrievedChunk`）、`knowledge-base` 把「知识库 + 授权集合」都备齐了，但**检索要吃到数据，前提是先有文档被解析入库**——而 `documents` 实体、文件存储、MinerU 解析、`ingest_jobs` 目前全部不存在（`app/models/` 无 `document`，`integrations/` 无 `storage` / `mineru`，`app/tasks/` 目录不存在）。

解析是 RAG 链路的**前段**：上游为「上传的文件」，下游为「切分器要消费的 `content_list.json`」。本 change 交付这条前段的最小可用闭环——上传落库、哈希去重、MinerU 解析出结构化原料、以文档状态机 + Celery job 驱动并持久化进度——为随后的切分与向量化 change 铺路。

## What Changes

- **Document 实体**：归属 `kb_id`、文件名、哈希、大小、Mime 类型、存储路径、解析产物路径、状态机 `UPLOADED → PARSING → PARSED / FAILED`（展示层含 `PENDING` 全景，与实际状态机对齐）
- **文件存储** `FileStorage` 抽象：原始文件 + 解析产物统一落盘（本地文件系统实现，接口可切 MinIO）
- **MinerU 解析集成**：默认云 API v4（`model_version=vlm`），上传文件 → 轮询/下载 `content_list.json`，作为下游切分的唯一原料；超时显式、失败保留到 `error_message`
- **`ingest_jobs`**：一次文档入库的全景任务记录（本 change 落到解析阶段），`PENDING / RUNNING / SUCCESS / FAILED`，progress 进度，MySQL 为真相来源
- **Celery 任务**：`document_parse`，异步驱动 PARSING→PARSED/FAILED，幂等可重放
- **上传接口**：`POST /api/v1/knowledge-bases/{kb_id}/documents`（multipart），格式白名单、文件大小限制、库内哈希去重（409）、提交即返回文档 + 任务句柄；列表 / 详情 / 软删 配套

## Capabilities

### New Capabilities

- `documents`: 文档上传、文件存储、MinerU 解析、文档状态机与 ingest job 进度

### Modified Capabilities

（无——不改变既有 `knowledge-base` / `rag-orchestration` / `project-scaffold` 的能力要求）

## Impact

- **代码**：`app/models/`（`document.py`、`ingest_job.py`）、`app/integrations/`（新增 `storage.py`、`mineru.py`；接线 Celery）、`app/services/`（文档与解析编排）、`app/api/v1/documents.py`（上传/列表/详情/软删）、`app/schemas/`、`app/tasks/`（新增 Celery 任务）、`alembic/versions/`、`core/config.py`（新增存储/解析/Celery 配置）
- **依赖**：新增 `celery`、`redis`（broker）、HTTP 客户端（`httpx`，MinerU 云 API）；文件上传解析 `python-multipart`
- **配置**：新增 `STORAGE_ROOT` / `MINERU_*` / `CELERY_BROKER_URL` 等环境变量
- **兼容性**：`documents` 为空表时无任何影响；上传后无切分/向量化消费方，解析产物以纯文件形式落盘（不建 `chunks` 表）
- **非目标**：切分（`domain/chunking` L0–L5）、向量化与 Milvus 写入、文档重建索引（reindex）、问答端点、前端上传界面——分别由后续 `chunking` / `embedding-ingest` / `qa` / 前端 change 覆盖