## Context

动机见 `proposal.md` 的 Why（两条 MUST 未落地）。与实现方式相关的现状：

- **实体与会话**：`get_session_factory()` 已设 `expire_on_commit=False`（`core/db.py`），因此"中途提交后再访问 ORM 属性"不会触发意外懒加载。
- **事务归属**：`get_db()` 的约定（服务层只 `flush`，由调用方提交）**只覆盖 FastAPI 请求**。Celery 任务是自管事务：`tasks/ingest.py` 在任务体内自建会话并 `session.commit()`。当前三个服务函数（`resolve_parse` / `resolve_chunking` / `resolve_indexing`）都把「瞬态状态 + job RUNNING + 外部 I/O + 终态」放在**同一个未提交事务**里，`flush` 只在 I/O 结束后发生。
- **入口护栏形态**：任务侧是"只认起始态"的白名单——`_parse_document` 仅接受 `UPLOADED`；切分/向量化的入口在服务层要求 `PARSED`。这使"进程在瞬态被杀"的文档永久卡死。
- **向量化装配**：`integrations/embeddings.py` 的 `build_embeddings(settings)` 是唯一构造入口，当前无 `text_type`；`OpenAIEmbeddings` 具备 `model_kwargs` 透传额外请求体字段的入口（已确认）。
- **`text_type` 真实行为**（2026-09-14 实测，见 proposal.md 的 Why 表）：兼容端点接受并校验该参数（非法值 400），且**不传 == `query`**，与官方原生文档所述默认值 `document` 相反。

## Goals / Non-Goals

**Goals:**

- 让 `PARSING` / `CHUNKING` / `EMBEDDING` 三个瞬态状态**在外部 I/O 之前**就对外可查，并补齐缺失的 `PARSING` 赋值。
- 让"进程在瞬态中断"的文档**可重放恢复**，不出现永久进行中。
- 让入库编码**显式**使用 `document` 语义，两侧取值同源，并以测试锁定（防止静默回退到默认 `query`）。

**Non-Goals:**

- 查询侧（`text_type=query`）的实际接线与检索链路的 `instruct` 参数——归 `qa` change。
- 不改变状态集合、终态语义、Milvus collection schema、切分算法、HTTP 接口形态。
- 不引入"进度百分比"（`ingest_jobs.progress_*` 语义与页数回填不在本 change）。
- 不做对账任务扫孤儿向量（`ops` change）。

## Decisions

### D1. 瞬态可见性用"阶段切换点显式提交"实现，提交动作可注入

**选择**：三个服务函数各自在「置瞬态状态 + `job.status=RUNNING` + `job.stage`」之后、调用外部依赖之前，触发一次提交；提交动作通过**可注入的回调**表达（形如 `commit: Callable[[], None] | None = None`，默认取 `session.commit`），而不是服务层直接硬编码 `session.commit()`。

**理由**：
- 直接 `session.commit()` 会让服务层单测无法用"回滚隔离"（测试 fixture 常在结尾 rollback），注入回调既能在生产中真实提交，也让测试可以注入 spy 来断言**提交确实发生在 I/O 之前**——这正是 spec 新场景要验证的行为。
- 瞬态落库后，长任务期间任何只读查询都能观测到进行中状态与 `job RUNNING`，满足 spec 时序契约。

**备选**：
- *在任务层开两个会话（先提交状态，再开新会话做 I/O 与终态）*：状态与 I/O 的耦合点仍留在服务函数内部无法被单测覆盖，且会话生命周期管理复杂化。放弃。
- *依赖 `flush` 而非提交*：`flush` 不提交，其他连接读不到，等于没做。放弃。

### D2. 入口护栏从"只认起始态"改为"起始态或自身瞬态"

**选择**：放宽三个入口——
- `resolve_parse`：`UPLOADED` 或 `PARSING` 均可进入（`PARSING` 视为"上次未完成"，重新解析；`PARSED`/`READY`/`FAILED` 仍短路）。
- `resolve_chunking`：`PARSED` 或 `CHUNKING` 且当前无 `chunks` 可进入。
- `resolve_indexing`：`PARSED` 或 `EMBEDDING` 且存在 `is_recallable` chunk 可进入（入口原有的"非 `PARSED` 短路"放宽为也接受 `EMBEDDING`）。

**护栏有两处，MUST 同步放宽**：同一份准入判断在**任务层**（`tasks/ingest.py` 的 `_parse_document` 白名单、`_chunk_document`、`_embed_document`，以及阶段分派判定 `_is_parsed` / `_is_embeddable`）与**服务层**各存在一份。只改服务层不会生效——任务在到达服务函数之前就被任务层白名单拦掉。两处必须一并放宽，并以测试覆盖（否则中断文档仍然卡死）。

**边界**：本 change 只保证文档"**可被**重新驱动"，不提供自动恢复的触发渠道（如 reindex 端点、超时看门狗）——那属 `ops` change。因此 spec 场景的验证方式是"显式再次调用对应任务/入口"而非"自动收敛"。

**理由**：瞬态一旦提交就可能在崩溃后残留。若入口继续只认起始态，这些文档将永久卡住——违反 spec 新增场景「任务被中断后不留永久进行中状态」。三个阶段的幂等性由**已有机制**保证，不会因放宽而重复产出：解析成功才写 `artifact_path` 与 `PARSED`；切分入口有"已有 chunks 则短路"；向量化入口有"写前先清同文档旧向量"（既有 D3）。

**备选**：*新增超时看门狗把陈旧瞬态打回起始态*——引入定时任务与阈值配置，超出本 change 需要（YAGNI）；先靠"可重放"覆盖，看门狗留待 `ops` change。

### D3. `text_type` 走 `model_kwargs={"extra_body": {...}}`，且取值必需显式传入

**选择**：
- 在 `domain/` 下定义两侧取值的**单一来源常量**（`document` / `query`），不散落字符串。
- `build_embeddings(settings, *, text_type)`：`text_type` 是**必传的 keyword-only 参数**（不设默认值），经 `model_kwargs={"extra_body": {"text_type": text_type}}` 透传。
- 入库调用点（`index_service`）传 `document`；查询侧由 `qa` change 传 `query`。

**理由（含实测证据）**：
- **不能写成 `model_kwargs={"text_type": ...}`**：openai SDK 的 `client.embeddings.create()` 是强类型签名，langchain 会把 `model_kwargs` 直接展开成调用 kwargs。实测抛 `TypeError: Embeddings.create() got an unexpected keyword argument 'text_type'`——主选方案在编码**第一次调用**时即崩，属实现期必然踩到的坑，故在此记录。
- **`extra_body` 是正确路径**：它是 openai SDK 的标准透传机制。实测在**默认** `check_embedding_ctx_length=True`（生产走的分批路径）下，请求体顶层包含 `text_type`，且与 `dimensions` 并存无冲突；不传时该字段缺席。
- **不设默认值**：若客户端默认 `document`，查询侧漏传会静默按文档侧编码——同样是"无报错却语义错误"，与本次事故同型。必传强制两侧调用点各自显式表态，与 spec「两侧取值 MUST 同源、MUST NOT 依赖默认」一致。

**备选**：*包装自定义 client 子类覆写 `create`* —— 引入对 SDK 内部结构的耦合，收益不足，放弃。*默认 `document`* —— 见上，放弃。

### D4. `text_type` 以"请求体断言"测试守护

**选择**：新增单测断言 `build_embeddings` 构造出的客户端在编码时，请求体携带 `text_type=document`（默认）且可被显式覆盖为 `query`；实现方式用 `httpx.MockTransport` 或对 `_invocation_params` 的断言，不打真实网络。

**理由**：本次事故的本质是"漏传即静默改变语义且无任何报错"。只有把"请求确实携带该字段"变成红灯测试，才能防止回归。

### D5. 文档字符串与实现对齐

**选择**：修正 `resolve_parse`（及相邻函数）docstring 中与实现不符的状态机描述，并说明"中途提交"的存在与理由，避免下一位读者再次误判。

## Risks / Trade-offs

- **[中途提交削弱了"失败不留半套"的原子性]** → 中途提交的只有**状态列与 job 行**，业务数据（`chunks` 行、Milvus 向量）仍在后续事务内；结合 D2 的可重放入口与既有的"写前先清旧向量"，中断后重放收敛到一致结果。
- **[服务层提交偏离既有分层约定]** → 该约定原文只约束 FastAPI 请求路径；本 change 把例外限定在"入库阶段切换点"，并通过注入回调表达，在 design 与 docstring 双处记录。
- **[瞬态可见带来"卡在进行中"的观感]** → 这正是可观测性的目的（此前是"看不到"）；恢复路径为任务重放，属 `ops` 范畴的看门狗不在本 change。
- **[两处护栏漏改]** → 任务层与服务层各有一份准入判断，漏改任一处则"中断可重放"完全不生效（且不会报错，表现为文档永久停在瞬态）→ 以测试同时覆盖两处（任务入口 + 服务入口）。
- **[兼容层默认值依赖风险]** → 显式传参后不再受默认值影响；若服务端未来改变默认或拒绝该参数，测试会先失败（而非静默降级）。
- **[测试隔离]** → 注入 no-op/spy 提交回调，保持服务层单测原有的回滚隔离不变。
- **[并发重放]** → 护栏放宽后，理论上允许同一文档被并发重放；既有语义不变（Celery 串行 + 状态护栏 + 向量化先删后写），本 change 不新增分布式锁（记为后续项）。

## Migration Plan

1. 无数据迁移、无 schema 变更、无接口变更；部署即生效，回滚即 revert。
2. 顺序：`text_type`（独立、低耦合）→ 瞬态提交边界 → 入口放宽 → docstring 与门禁。
3. 每个改动按 TDD：先写失败测试（提交时序 / 请求体断言 / 中断重放），再实现。

## Open Questions

- 查询侧 `text_type=query` 的接线位置与是否启用 `instruct` 参数（官方称 query 侧可带来 1%–5% 提升，但计入 token）——归 `qa` change，依据检索评测数据决定。
- 瞬态"卡死"是否需要超时看门狗（把超过阈值的瞬态自动打回可重放态）——归 `ops` change，本 change 只保证可重放。
