## 1. 入库编码语义（`text_type=document`）

- [x] 1.1 红灯：新增单测断言入库编码请求体携带 `text_type=document`（用 `httpx.MockTransport` 或对 `_invocation_params` 断言，不打真实网络），并断言可被显式覆盖为 `query`
- [x] 1.2 在 `domain/` 定义两侧取值的单一来源常量（`document` / `query`），零框架依赖；确认 `integrations/` 消费方向符合 `test_import_boundaries.py` 的边界纪律
- [x] 1.3 `integrations/embeddings.py` 的 `build_embeddings(settings, *, text_type)` 以**必传** keyword-only 参数接收取值，经 `model_kwargs={"extra_body": {"text_type": text_type}}` 透传；入库调用点（`index_service`）传 `document` 常量
- [x] 1.4 断言透传在生产默认分批路径（`check_embedding_ctx_length=True`）下仍生效、请求体顶层含 `text_type`；确认实现**不得**写成 `model_kwargs={"text_type": ...}`（openai SDK 强类型签名会抛 `TypeError`，已实测）
- [x] 1.5 真实端点抽查（一次调用）：显式 `document` 与不传所得向量不同，确认修复后入库路径确实走文档侧语义

## 2. 瞬态状态在外部 I/O 前可见（提交边界）

- [x] 2.1 红灯：断言"瞬态状态 + `job RUNNING`"的提交发生在调用外部依赖**之前**（向服务函数注入 spy 提交回调，记录调用点与 I/O 调用点的先后）
- [x] 2.2 红灯：断言解析阶段开始时文档状态为 `PARSING`（当前实现从未赋值）
- [x] 2.3 `resolve_parse`：补 `PARSING` 赋值，并在进入解析 I/O 前触发阶段提交（注入回调，默认 `session.commit`）
- [x] 2.4 `resolve_chunking`：`CHUNKING` 与 job `RUNNING`（stage `CHUNK`）在读取产物/切分前提交
- [x] 2.5 `resolve_indexing`：`EMBEDDING` 与 job `RUNNING`（stage `EMBED`）在 `ensure_collection` / 编码 / 写 Milvus 前提交
- [x] 2.6 失败路径落库：三个阶段失败时 `FAILED` 与错误信息同样被提交（不得因中途提交而丢失）
- [x] 2.7 任务层配合：`tasks/ingest.py` 三个任务确保终态提交与分派顺序正确（提交后再读状态分派下一阶段）

## 3. 中断后可重放（入口放宽）

- [x] 3.1 红灯：模拟"进程在瞬态被杀"留下的文档（`PARSING` / `CHUNKING` / `EMBEDDING`），**经任务层入口**（`tasks/ingest.py`）重新驱动，断言到达终态而非被任务层白名单拦掉（表现为永久卡死）
- [x] 3.2 `resolve_parse`（服务层）与任务层 `_parse_document` 白名单**同步**放宽为接受 `UPLOADED` 或 `PARSING`；`PARSED` / `READY` / `FAILED` 仍短路
- [x] 3.3 `resolve_chunking` 与 `_chunk_document` **同步**放宽为接受 `PARSED` 或 `CHUNKING`（且当前无 `chunks`）；已切分仍短路
- [x] 3.4 `resolve_indexing` 与 `_embed_document` **同步**放宽为接受 `PARSED` 或 `EMBEDDING`（且含 `is_recallable` chunk）；保持"写前先清同文档旧向量"的重放收敛
- [x] 3.5 回归确认：放宽入口后"重放幂等"场景仍成立（已 `PARSED`/`READY` 的文档不重复切分与编码）
- [x] 3.6 核实阶段分派判定（`_is_parsed` / `_is_embeddable`）不因瞬态阻断重放，并在 design 已记录"只保证可重放、自动恢复渠道归 `ops` change"的边界

## 4. 文档与实现对齐

- [x] 4.1 修正 `resolve_parse` 及相关函数的 docstring：状态机描述与实现一致，并说明本 change 引入的"阶段切换点提交"及其理由

## 5. 门禁与收尾

- [x] 5.1 `uv run pytest` 全绿、`uv run ruff check .` 与 `uv run mypy app` 零错误
- [x] 5.2 同步主 spec：`openspec/specs/documents/spec.md` 与 `openspec/specs/vector-index/spec.md` 合入 delta，归档本 change 至 `openspec/changes/archive/2026-09-14-fix-ingest-state-and-embedding-contract/`
