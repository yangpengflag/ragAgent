## Context

- 已归档 `document-chunking`（independent change）：`content_list.json → list[Chunk]` 落 MySQL `chunks` 表，child 标记 `is_recallable=true`，文档切分完成回 `PARSED`、`ingest_job.stage=CHUNK`。
- 既有装配件：`integrations/embeddings.py`（DashScope `qwen3.7-text-embedding`，dim 1024、batch 20、`text_type` 策略）、`integrations/vectorstore.py`（langchain-milvus 已装，`partition_key_field=kb_id`、主键 `chunk_id`、`auto_id=False`、关闭 dynamic field）。**素材证明 langchain-milvus 自动建表不可依赖（风险 R6）**。
- 已有模型：`Document.status ∈ {UPLOADED,PARSING,PARSED,CHUNKING,FAILED}`、`IngestJob.status` + `stage`（String 列）；`chunks` 含 `is_recallable`/`parent_id`。
- 检索过滤需 `kb_id` 下推（project.md：权限下推、禁止先检索再过滤）。
- 命名说明：change 名（`document-embedding-index`）新增 `vector-index` cap 并修改 `documents` cap，"事务名"非单一 cap 名（project.md 同类先例见 `document-chunking`）。
- 动机见 `proposal.md`；行为契约见两个 spec delta。

## Goals / Non-Goals

**Goals:**
- Milvus collection 显式建表 + child chunk 批量向量化写入，双写（MySQL/Milvus）以 `chunk_id` 对齐。
- 文档状态推进 `PARSED → EMBEDDING → READY`，沿同一 `ingest_job` 推进 `stage=EMBED`。
- 幂等、可重放、失败补偿；软删同步清向量。
- `chunks` 字段与 `RetrievedChunk` 契约对齐，检索零转换消费。

**Non-Goals:**
- 纯域切分与 `chunks` 落库（`document-chunking`）。
- 检索/问答端点与引用渲染（`qa` change）；稀疏/重排腿（二期）。
- 对账任务扫孤儿 / reindex（ops change）；前端界面（前端 change）。

## Decisions

### D1. Milvus collection 显式建表；写入走 langchain-milvus，删除走 pymilvus

**选择**：`integrations/milvus.py` 新增：
- `ensure_collection(settings)`：用 *pymilvus* 显式 `create_collection`（collection 名与 database 复用既有 `settings.milvus_collection` / `settings.milvus_database`，schema 与 `build_milvus_kwargs` 对齐；`chunk_id` 主键 `auto_id=False`、`content`、`vector`【FloatVector, dim=embed_dim】、`kb_id` String 作 partition key、`document_id` String）。已存在则幂等返回。
- 写入走既有 `integrations/vectorstore.py` 的 `build_vectorstore`（`Milvus` 实例），构造时显式禁用自动建表（collection 已由 `ensure_collection` 建好）。
- `delete_document_vectors(settings, kb_id, document_id)`：pymilvus 按 `expr`（`document_id == ... and kb_id == ...`）删除，删空幂等。

**理由**：既有 R6 证明 langchain-milvus 自动建表不可依赖（dynamic field/字段推导）；schema 是检索/filter 契约，主动权在我。删除用 pymilvus 直连避开 langchain 删除语义差异。
**备选**：全走 langchain-milvus —— 自动建表槽点依旧 + 无按 expr 批量删接口；放弃。

### D2. 状态机与 `ingest_job.stage`：`EMBEDDING` 瞬态 → `READY`

**选择**：向量化任务对已切分（`PARSED` 且有 `is_recallable` chunks）文档：置 `EMBEDDING`（job `RUNNING`, stage `EMBED`）→ 编码 + 写 Milvus → 置 `READY`（job `SUCCESS`, stage `EMBED`）。入口校验文档状态与是否有待向量化 chunk，非就绪直接短路（幂等）。失败置 `FAILED`，保留 error。

**理由**：`README` 由向量化完成定义（project 定稿）；`EMBEDDING` 是可见进行态（长 I/O，展示层需要）。
**备选**：合成一个中间终态 `INDEXED` —— 不必要，`READY` 即终态。

### D3. 幂等与失败补偿：写入前幂等清旧向量

**选择**：`document_embed` 开始先对同文档旧向量做一次 `delete_document_vectors`（幂等）再编码写入，保证同文档重放不残留旧 `chunk_id`。`chunk_id` 为 UUID v7 幂等键；失败时已写入向量可通过 `document_id` 可辨识、可清理。编码批量走既有 `dashscope_embed_batch_size`（20）。

**理由**：向量写是外部副作用，先删后写把重放收敛为"最终只剩本批次"；幂等键 UUID 复用既有 ids 规约。
**备选**：upsert/insert-if-absent —— 同 key 覆盖语义依赖 langchain 实现，不可靠；先删后写更直白。

### D4. 软删一致性：MySQL 为准，向量滞后清理

**选择**：软删（`documents`）时：
1. 事务内软删 `document` + 其 `chunks`，提交。
2. 提交后调 `delete_document_vectors` 清 Milvus。
3. 清向量失败**不阻塞软删**，记日志、留待对账任务兜底（本 change 提供清理入口，不做后台重试循环）。

**理由**：MySQL 是真相，`deleted_at` 已让检索过滤排除（`kb_id` 下推 + 全局软删过滤）；Milvus 删除是外部副作用无法进事务。先落库后清向量，崩溃最坏留孤儿向量（可对账清理），但不会出现"向量已删、chunk 仍可查"的反向不一致。
**备选**：先清向量再落库 —— 崩溃导致向量已删但 chunk 未删（可再检索已软删内容），违反"软删即不可检索"，更糟；放弃。

### D5. Milvus 写入前确保 collection 存在

**选择**：向量化任务落库前调用 `ensure_collection`（幂等），保证第一个 chunk 写入前 schema 在场；`build_vectorstore` 禁用自动建表以避免与显式 schema 冲突。

**理由**：规避 R6（从未建库到首单写入之间的窗口）；无 collection 时显式建，避免 langchain 隐式建出错误 schema。

### D6. 配置：复用已有 embed 项，补 Milvus 超时

**选择**：`embed_dim`/`embed_model`/`embed_batch_size` 沿用既有 `dashscope_embed_*`；补 `MILVUS_TIMEOUT_SEC`（显式超时，backend-conventions）。向量模型不硬编码维度（从库 `embed_dim` 读）。

**理由**：既有配置已覆盖编码；Milvus 操作须显式超时防无限等待。

## Risks / Trade-offs

- **[软删清向量滞后]** 崩溃/删除失败留孤儿向量 → 软删不阻塞 + `delete_document_vectors` 幂等 + 日志，对账任务（ops change）扫"Milvus 存在但 chunk 已软删"记录。
- **[向量写失败/半套]** 批量写中途失败 → 文档 `FAILED` + error；已写 chunk 以 `document_id` 可辨识，`document_embed` 开头幂等清旧向量后重放，不产生重复存活向量。
- **[混维度风险]** collection 维度固定于首建 → `ensure_collection` 幂等建表锁定 dim；换模型需整库重建或新 collection（project 约定），本 change 不自动迁移。
- **[外部副作用无事务]** Milvus 写/删不参与 MySQL 事务 → 用「先删后写」「先落库后清向量」收敛到"MySQL 为真相 + 孤儿可对账"。

## Migration Plan

1. Alembic：`documents.status` 枚举 MODIFY 追加 `EMBEDDING/READY`（可回滚还原）。无新表。
2. `integrations/milvus.py`（`ensure_collection`/`delete_document_vectors`）+ 单测（Mock/独立 test database）。
3. `index_service`：状态机 `PARSED→EMBEDDING→READY`、写前清旧、失败回滚语义。
4. `tasks/ingest.py`：新增向量化任务并在切分/解析后分派。
5. 软删接线：`document_service` 提交后清向量。
6. 配置 `MILVUS_TIMEOUT_SEC` 入 `config.py` + `.env.example`。
7. 门禁：`pytest`/`ruff`/`mypy` 全绿；无数据迁移（枚举扩展）。

## Open Questions

- **`text_type` 查询/入库切换**：入库文档向量与检索 query 向量是否需区分 `text_type`（DashScope ingest vs query）——既有 embeddings 装配已走 OpenAI 兼容单模型，是否需要按 project.md 的说法显式区分；本 change 只负责入库侧，检索方在 `qa` change 定夺。