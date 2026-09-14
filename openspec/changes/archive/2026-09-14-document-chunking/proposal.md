## Why

文档解析后停在 `PARSED`，产物 `content_list.json` 只是原料。要让它可被检索/问答消费，必须先切成检索单元 `Chunk` 并落库——这是建索引的前置。本 change 只做「切分」，把解析产物转成带结构与定位的 `Chunk` 持久化到 MySQL；向量化写入 Milvus 由独立的 `document-embedding-index` change 承接。

## What Changes

- **新增切分域（`domain/chunking`）纯函数**：把 MinerU `content_list.json` 解析为 `list[Block]` → 按 `text_level` 还原章节树 → 按块类型贪心打包成 `Chunk`，注入结构面包屑（L0–L4a）。含表格双表示、代码/公式边界、tiktoken 代理计数。确定性、零 I/O。
- **新增父子块（L4c）**：Child chunk（`is_recallable=true`，供向量化召回）与 Parent chunk（供生成）均在切分期产出并落 MySQL。
- **新增 `chunks` 表**：UUID v7 主键、`kb_id`/`document_id` 归属、`parent_id` 自关联、`content`/`section_path`/`page_idx`/`bbox`/`block_type`/`is_recallable`。
- **切分驱动 + 状态机**：Celery 任务把 `PARSED` 文档推进到 `CHUNKING`（切分中瞬态），chunks 落库完成后回 `PARSED`（= 索引原料就绪）；`ingest_jobs` 复用同一 job 推进 `stage=CHUNK`、progress，MySQL 为真相。幂等可重放。
- **软删清洗**：软删文档时同步软删其 `chunks` 行（本 change 尚无向量可清）。
- **配置**：切分阈值（各类型 target/max、`overlap_ratio` 默认 0 关）入 `config.py` 与 `.env.example`。

**Breaking**：`documents.status` 枚举追加 `CHUNKING`（存量兼容见 database-conventions）。

## Capabilities

### New Capabilities

- `chunking`: 文本切分——从 `content_list.json` 到 `Chunk` 的纯领域管线（Block 解析、章节树、动态打包、面包屑、父子块、overlap 兜底），确定性、零 I/O，全仓 TDD 主战场；含 `chunks` 落库与切分驱动。

### Modified Capabilities

- `documents`: 文档解析完成后可触发切分：状态 `PARSED`（索引原料就绪）与切分中瞬态 `CHUNKING` 的可查性，列表/详情携带切分进度；软删需同步软删其 chunks。

## Impact

- **代码**：`backend/app/domain/chunking/`（新增纯域）、`backend/app/models/chunk.py`（新增）、`backend/app/services/`（新增 `chunk_service`，推进到 `CHUNKING`/回 `PARSED`）、`backend/app/tasks/ingest.py`（扩展切分任务）、`backend/app/services/document_service.py`（软删接线 chunk）。
- **数据库**：新增 `chunks` 表迁移；`documents.status` 枚举追加 `CHUNKING`；`ingest_jobs` 复用（`stage` 走既有字符串列，无结构变更）。
- **依赖**：`tiktoken`。
- **不做**：向量化/Milvus/`EMBEDDING`/`READY`、软删清向量（`document-embedding-index` change）；检索问答（`qa` change）；对账任务、reindex（ops change）；前端界面（前端 change）。