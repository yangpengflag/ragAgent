## Context

- 已归档 `document-upload-and-parse`：文档可上传 → MinerU 解析 → `content_list.json` 落盘，状态停在 `PARSED`、`ingest_job` 停在 `SUCCESS`（stage=`PARSE`）。
- 检索消费契约 `RetrievedChunk`（domain/retrieval）已定：`chunk_id / kb_id / document_id / parent_id / content / score / page_idx / bbox`——本 change 的 chunk 产出须对齐，检索侧才能零转换消费。
- 已有模型：`Document.status ∈ {UPLOADED,PARSING,PARSED,FAILED}`、`IngestJob.status` + `stage`（String 列，固定 `PARSE`）。
- `project.md` 已定稿切分档位（text 512/768、table 1024/2048、code 768/1024、equation 256/512）、tiktoken×1.15 代理、父子块默认开、overlap 默认关。
- 动机见 `proposal.md`；行为契约见两个 spec delta。向量化/Milvus 明确归 `document-embedding-index`。
- 命名说明：change 名（`document-chunking`）同时新增 `chunking` cap 与修改 `documents` cap，故该名是"事务名"而非单一新增 cap 名（project.md 同类先例：`auth-and-users` 引入 `identity`+`authentication`）。`document-embedding-index` 同理。

## Goals / Non-Goals

**Goals:**
- 纯域切分器：`content_list.json → list[Chunk]`，确定性、零 I/O、毫秒级单测。
- `chunks` 表落库 Child/Parent；文档状态引入切分中瞬态 `CHUNKING`，切分完成回 `PARSED`（原料就绪）。
- 沿同一 `ingest_job` 推进 `stage=CHUNK`；软删同步软删 `chunks`。
- `chunks` 字段与 `RetrievedChunk` 契约对齐，`is_recallable` 标记可召回子块供下游向量化。

**Non-Goals:**
- 向量化/Milvus 写入/`EMBEDDING`/`READY`、软删清向量（`document-embedding-index`）。
- 检索/问答端点（`qa` change）。
- overlap 开箱（L5 默认关）；Contextual Retrieval（L4b）。
- 对账任务扫孤儿 / reindex（ops change）；前端界面（前端 change）。

## Decisions

### D1. 切分器为纯函数，数据契约与检索侧对齐

**选择**：`domain/chunking` 提供纯函数与 dataclass：
- `Block`（MinerU `content_list.json` 元素：`type`/`text_level`/`text`/`page_idx`/`bbox`/`images`）；`Chunk`（`RetrievedChunk` 对齐字段 + `section_path` + `block_type` + `is_recallable`）。
- `blocks_from_artifact(path) -> list[Block]`、`build_chunks(blocks, cfg) -> list[Chunk]`；token 计数用可插拔 `TokenCounter`（默认 tiktoken `cl100k_base` ×1.15）。
- `Chunk.id` **以字符串（UUID hex）呈现**，与 `RetrievedChunk.chunk_id: str` 及 MySQL `chunks.id`、Milvus pk 复用链路对齐（B 写 Milvus 前置）。

**理由**：`domain/` 铁律要求零 I/O 纯函数，是全仓 TDD 主战场；字段与检索契约同名，下游零转换。
**备选**：LangChain splitter —— 无法表达结构树/类型档位/父子块，拒绝。

### D2. `chunks` 表：Child 与 Parent 双写，`parent_id` 自关联

**选择**：新增 `chunks` 表：`id`（UUID v7）、`kb_id`（FK）、`document_id`（FK）、`parent_id`（自关联，Child→Parent；无父子则自身或 NULL）、`content`（Text 大字段）、`section_path`、`page_idx`、`bbox`（JSON 容错读取）、`block_type`、`is_recallable`（bool，真=Child，入向量候选）。
- 列表类查询用 `load_only` 排除 `content`（`SELECT *` 禁令，database-conventions）。

**理由**：单一事实源，软删清理与二次鉴权共用一张表。
**备选**：父子分两表 —— 过度建模，同文档同生命周期，放弃。

### D3. 状态机与 `ingest_job.stage`：切分中 `CHUNKING` 瞬态，完成回 `PARSED`

**选择**：`DocumentStatus` 追加 `CHUNKING`。切分在入库任务内：置 `CHUNKING`（job `RUNNING`, stage `CHUNK`）→ 切分落库 → 置回 `PARSED`（job `SUCCESS`, stage `CHUNK`）。`PARSED` 语义扩为"解析 + 切分完成、索引原料就绪"（chunks 可查）。幂等：任务入口查文档状态与已有 chunks，已切分直接返回。失败置 `FAILED`，不留下半套 chunks（事务内写）。

**理由**：模型注释原先预留 `CHUNKING`；`PARSED` 本就是"原料就绪"，切分不改变其"可被消费"含义，仅把原料从 `content_list.json` 细化为 `chunks`。避免为切分引入游离终态，把 `READY` 预留向量化 change。
**备选**：切分管到新终态 `CHUNKED` —— 与 project 全景状态机不符且需再迁移，放弃。

### D4. 软删清洗：chunks 与文档同事务软删

**选择**：软删在既有 `document_service` 的同一事务内，对 `document` 与其 `chunks` 均置 `deleted_at`（全局过滤已让两者都不出现）。本 change 无向量，不做 Milvus 清理（向量化 change 补充删向量步骤）。

**理由**：事务内保证原子，崩溃不留半套；既有无软删全局过滤钩子复用。
**备选**：异步清 chunk —— 不必要，行删除属本地事务，放弃。

### D5. 配置：切分阈值进 `ChunkConfig`，domain 不感知 Settings

**选择**：新增 `CHUNK_*_TARGET/MAX_TOK`（text/list/table/code/equation）、`CHUNK_OVERLAP_RATIO`（默认 0 关）与既有 `dashscope_embed_*` 无关。`Settings` 组装为 `ChunkConfig`（dataclass），`build_chunks` 只收 `ChunkConfig`。

**理由**：backend-conventions 要求可配阈值且 domain 纯函数不 import config。

### D6. overlap（L5）与 Contextual（L4b）不入默认路径

**选择**：overlap 默认关（ratio 0）、L4b 不做；结构面包屑（L4a）默认注入，`is_recallable` 承载 small-to-big。为评测预留 `overlap_ratio` 配置位，读 0 直通。
**理由**：project 定稿 L5 默认关、L4b 需评测门禁；YAGNI 不为开关铺全参数面。

## Risks / Trade-offs

- **[切分耗时]** 超大文档纯函数切分耗时 → 在 Celery worker 内串行（不并行多文档），project 内存限制下稳妥。
- **[枚举扩展存量]** `documents.status` 追加 `CHUNKING`（`native_enum=False` VARCHAR+CHECK）→ Alembic MODIFY 列，随 `chunks` 表同一次迁移，规避分片风险。
- **[大字段查询]** `chunks.content` 大字段 → 查询显式 `load_only` 排除，禁 `SELECT *`。
- **[`PARSED` 语义扩展]** 复用 `PARSED` 表达"已切分" → 用 `job.stage` 与存在性查询（chunks 计数）区分是否已切分，避免仅凭 status 误判；向量化 change 依赖 `is_recallable` 判定，冲突面小。

## Migration Plan

1. Alembic 一次迁移：建 `chunks` 表；`documents.status` 枚举 MODIFY 追加 `CHUNKING`。可回滚（down 删表 + 还原枚举）。
2. `domain/chunking` 纯域 + 单测（RED→GREEN）：Block 解析、章节树、类型档位、父子块、面包屑、确定性。
3. `chunks` 模型 + `chunk_service`（状态机 `CHUNKING`→`PARSED`、事务内落库、软删接线）。
4. Celery 切分任务 + `ingest_job` stage 推进。
5. 配置补 `config.py` + `.env.example`（`CHUNK_*`）。
6. 门禁：`pytest` / `ruff` / `mypy`（领域层 `--strict`）全绿；无数据迁移（新表 + 枚举扩展）。

## Open Questions

- **vector-index 如何消费 `is_recallable`/Parent**：属 `document-embedding-index`，本 change 只保证产出对齐 `RetrievedChunk`。
- **是否引入"已切分"专属状态位**：当前用 `job.stage` + chunks 存在性表达，如后续展示层需要显式位再加，不现在猜字段。