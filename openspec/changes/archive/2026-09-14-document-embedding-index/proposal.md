## Why

`document-chunking` 已把解析产物切成 `Chunk` 并落 MySQL，但还没有可被向量检索命中的索引。要让问答端召回，必须把 `Chunk`（child）向量化写入 Milvus——这是 RAG 检索的第一入口。本 change 把文档状态机从 `PARSED` 推进到 `EMBEDDING → READY`，并落地软删清向量的一致性。

## What Changes

- **向量化与 Milvus 落库**：把 `is_recallable` 的 child chunk 批量编码（DashScope `qwen3.7-text-embedding`，1024 维）写入 Milvus；chunk 元数据已在 `chunks` 表，本 change 负责向量侧写入与双写一致性。
- **Milvus collection 显式建表**：用 pymilvus 按约定 schema 创建（主键 `chunk_id` `auto_id=False`、`content`、`vector`、`kb_id` partition key、`document_id`），不依赖 langchain 自动建表（既有风险 R6）。
- **状态机推进**：`PARSED`（含 chunks）→ `EMBEDDING`（向量化中）→ `READY`（可检索）；沿用同一 `ingest_job` 推进 `stage=EMBED`，MySQL 为真相。
- **软删清向量**：软删文档同步删除其 Milvus 向量与软删 chunk 行；重复软删幂等。
- **失败补偿**：向量化失败文档置 `FAILED`，可辨识、可清理重放（开头幂等清旧向量）。
- **配置**：复用已有 `dashscope_embed_*`；补 Milvus 侧超时等。

**Breaking**：`documents.status` 枚举追加 `EMBEDDING / READY`。

## Capabilities

### New Capabilities

- `vector-index`: 向量化与索引——`Chunk → embedding → Milvus` 落库，含 collection schema 显式创建、批量/幂等/可重放、失败补偿与软删清向量，并驱动文档推进到 `READY`。

### Modified Capabilities

- `documents`: 文档解析+切分完成后可继续向量化：状态推进 `EMBEDDING→READY`、列表/详情携带索引进度；软删需同步清理 Milvus 向量（由「无向量可清」变为「同步清索引」）。

## Impact

- **代码**：`backend/app/integrations/milvus.py`（新增 `ensure_collection`/`delete_document_vectors`）、`backend/app/integrations/vectorstore.py`（装配调整，禁自动建表）、`backend/app/services/index_service.py`（新增，状态机推进）、`backend/app/tasks/ingest.py`（新增向量化任务）、`backend/app/services/document_service.py`（软删接线清向量）。
- **数据库**：`documents.status` 枚举追加 `EMBEDDING/READY`（迁移）；`ingest_jobs` 复用未见结构变更。
- **依赖**：`pymilvus`（已随 langchain-milvus 装）、DashScope 向量模型（openai 兼容端，已配）。
- **系统**：首个 `chunks` 向量写入时触发 Milvus collection 显式创建；软删增加外部副作用删除步骤。
- **不做**：检索/问答端点与引用渲染（`qa` change）；纯域切分与 `chunks` 落库（`document-chunking`）；对账任务扫孤儿 / reindex（ops change）；前端界面（前端 change）。