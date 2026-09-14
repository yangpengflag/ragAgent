# Design: rag-orchestration-langchain

## Context

RAG 链路未动工：`backend/app/domain/` 与 `backend/app/integrations/` 为空目录。既有架构铁律（见 `openspec/project.md`）：

- `domain/` 零 I/O、零框架依赖，是 TDD 主战场
- 分层 `api/ → services/ → domain/（纯函数）+ integrations/（外部适配）`
- Milvus 2.5.10 Standalone（database `ragagent`），KB 级用 partition_key 隔离
- DashScope `qwen-plus`（生成）/ `qwen3.7-text-embedding` 1024 维（向量）经 OpenAI 兼容模式接入
- 权限模型：`user_kb_grant(user_id, kb_id, role)`，"权限下推，禁止先检索再过滤"已定稿

LangChain 生态自 2025-10 起处于 1.x 稳定态：`langchain-core` 为接口基座，partner 包（`langchain-openai` / `langchain-milvus`）各自独立发版；主包 `langchain` 转向 Agent Runtime；`langchain-community` 进入冻结维护态。

## Goals / Non-Goals

**Goals:**

- 以最小依赖面引入 LangChain 组件基座，建立 `integrations/` 集成边界与替换约定
- 建立 LangSmith 观测的多粒度开关与 fail-open 语义，满足企业部署"观测非必需、出网可控"
- 定义带权限过滤的 Retriever 契约与授权解析路径
- 明确切分器、prompt、评测产物的归属，防止被框架吸走

**Non-Goals:**

- 不实现 QA 端点、ingest 管道、切分器本身（后续 change 消费本基座）
- 不引入 LangGraph（纯 RAG 一条链：无分支、无循环、无工具调用）
- 不引入稀疏检索腿 / 重排（二期，dense-only 先行）
- 不做多租户、文档级 ACL（项目非目标）

## Decisions

### D1: 依赖面收敛为 3+1 包

```
langchain-core      # Runnable 接口、回调协议、测试 Fake 基座
langchain-openai    # ChatOpenAI + OpenAIEmbeddings，base_url 指向 DashScope compatible-mode
langchain-milvus    # VectorStore（官方 partner 包，支持 partition_key）
langsmith           # 观测（可开关；开启时才真正工作）
```

**备选与排除理由**：

| 备选 | 排除理由 |
|---|---|
| `dashscope` 官方 SDK 直连 | 无统一 Runnable 接口，观测/换模型需自建适配，恰是本 change 要避免的 |
| `langchain-community` 的 `DashScopeEmbeddings` | 整包重、传递依赖多，1.0 后冻结维护；compatible-mode 的 `/embeddings` 端点功能等价，无需为它开洞 |
| `langchain` 主包 | 1.0 转向 Agent Runtime，纯 RAG 用不到；减少升级爆炸半径 |
| Langfuse 替代 LangSmith | 不互斥：D5 的 endpoint 可配置使 Langfuse（自托管，OTel 兼容）成为部署期可选目标，代码契约一致 |

### D2: 集成边界与"两不包"纪律

LangChain 组件封装在 `integrations/`，但**不追求包打天下**——只在替换动机真实的地方建自有接口：

```
backend/app/integrations/
├─ llm.py          # 构造 ChatOpenAI(base_url=DASHSCOPE_*)；薄工厂，不建 protocol
├─ embeddings.py   # 构造 OpenAIEmbeddings；同上
├─ vectorstore.py  # langchain-milvus 直接暴露，不再包一层 protocol
│                   #   （短期内不换向量库，包了就是 wrapper of wrapper）
├─ retriever.py    # ★ 自定义逻辑所在：授权集合 → 服务端过滤 → 检索
└─ tracing.py      # 观测开关装配（进程级 env + 请求级 context）
```

- **包的判定标准**：存在真实替换需求才建自有抽象。LLM/Embedding 换模型是项目明确预期（`qwen-plus` 可能换档），故工厂函数收口；VectorStore 无替换计划，直接暴露。
- **类型不越界**：`Document`、消息类型等 LangChain 类型不得出现在 `domain/` 或 `services/`；integrations 负责 LangChain 类型 ↔ 领域契约（`Chunk` / `RetrievedChunk` dataclass，定义在 `domain/`）的转换。review 硬规则。
- **`domain/` 铁律不动**：切分、召回融合算法、引用标注等纯函数不 import 任何 langchain 包。

**备选**：全自研适配层（每组件建 protocol）→ 拒绝，理由如上；services 直接 import langchain → 拒绝，类型泄漏 + 升级爆炸半径失控。

### D3: 切分器不进 LangChain

结构感知切分（project.md L0–L5：章节树、表格双表示、动态档位、父子块、面包屑）是项目差异化资产与 TDD 主战场。LangChain 通用 splitter 对结构树/双表示零覆盖，硬套即退化。切分器保持 `domain/chunking/` 纯函数（`list[Block] → list[Chunk]`），LangChain 仅在 ingest 下游（embedding 写入）被消费。ingest 编排归 Celery task + services 状态机，**不用 LCEL 表达**（LCEL 无法表达失败补偿/对账/状态迁移语义）。

### D4: 权限过滤与授权解析

```
请求（JWT → user_id）
   │
   ▼
授权解析：SELECT kb_id FROM user_kb_grant WHERE user_id = ?    ← MySQL 唯一真相源
   │  得到授权集合（默认不缓存 → 撤销即时生效，满足 spec 5s 上限）
   │  （预留 TTL 缓存配置位，默认关闭；开启时 TTL ≤ 5s）
   ▼
授权集合为空 → 直接返回空结果，不打向量库                       ← spec 短路要求
   ▼
Retriever(授权集合)
   │  过滤条件在检索查询内表达：
   │    expr: kb_id in [...]（兜底，必选）
   │    partition_key 剪枝：spike 实测后决定是否启用（见 R1）
   ▼
Milvus search → 领域契约 RetrievedChunk → services
```

- 授权集合为空时短路，不执行向量库查询（spec 场景要求）。
- **二次鉴权**（引用溯源返回 chunk 原文前再校验）属 API 层行为，归后续 QA change，本 change 只在 Retriever 契约上预留 `chunk → kb_id` 映射信息。

### D5: LangSmith 开关与 fail-open

- **进程级**：`LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` / `LANGSMITH_ENDPOINT`（endpoint 可配置 → 支持自托管 Langfuse / LangSmith 自托管，满足"出网目标受配置约束"）。缺省 = 关闭。
- **请求级**：`tracing_context` 上下文管理器，允许单请求覆盖进程默认（管理员调试会话开 trace）。请求级标记经请求上下文（同 request_id 机制）传递。
- **fail-open**：trace 上报失败仅记录日志（含 request_id），不冒泡为业务异常。验收测试模拟连接黑洞（不可达端点 + 超时），断言问答链路结果与观测关闭时一致。
- **prompt 不走 LangSmith Hub**：模板入仓常量（spec 要求版本化可追溯）。golden QA 评测脚本入仓（CI 门禁离线可跑），LangSmith Datasets/Evaluation 仅作面板。

### D6: LCEL 使用深度

仅问答生成链使用 Runnable 组合（retriever → prompt → llm → parser，流式输出经 astream）；ingest/状态机/Celery 编排不 LCEL 化（D3）。

**实现期澄清（任务 4.4 边界守卫生效后）**：D2 硬规则禁止 LangChain 类型进入 `services/`，因此链组装落在 `app/integrations/qa_chain.py`（LangChain 侧），services 只做编排调用与事务；prompt 文本作为入仓常量放在 `app/domain/generation/prompts.py`（纯字符串 + 纯渲染函数，零依赖、可评审、可版本化）。测试用 `langchain-core` 的 FakeChatModel/FakeEmbeddings，沿用 scaffold "测试不依赖外部模型服务" 的既有门禁。

## Risks / Trade-offs

- **[R1] partition_key 与 `kb_id in [...]` expr 组合行为未实测** → **已实测（spike 2026-09-13，Milvus 2.5.10 Standalone / database `ragagent`）**：① expr 过滤语义正确，20 kb × 500 条规模下单库/多库/wide expr（全量 20 库）结果集均严格落在授权集合内，零越权；② partition_key 字段可同时建 INVERTED 标量索引，与 expr 过滤共存无冲突；③ 同规模下 partition_key 剪枝带来约 2x 平均延迟收益（单库过滤 14.2ms vs 27.9ms），wide expr 6.6ms 正常。**决策：采用 partition_key + expr 双保险（expr 为权限边界必选，partition_key 为性能优化）**。遗留：性能数据为 10k 小规模，生产规模（百万级）的剪枝收益留 golden QA 阶段复测。
- **[R2] tracing 上报失败在网络黑洞下的实际阻塞行为未验证** → **已实测（spike 2026-09-13，langsmith 0.12.4）**：off / refused（端口快速拒绝）/ blackhole（非路由 IP 连接超时）三种条件下，10 次带 trace 的业务调用主线程耗时 496–607ms 无显著差异，**主线程零阻塞、零异常冒泡**；上报失败仅由后台线程以 warning 记录（API key 自动脱敏）。**决策：无需额外异步 handler 隔离层，直接采用 SDK 默认后台批量上报。** 两个落地注意：① LangSmith 自有 logger 的失败告警需在生产日志配置中归并/降噪；② 可用 `LANGSMITH_TIMEOUT_MS` 收敛后台重试窗口（黑洞时后台线程会按 connect timeout 10s → 重试 3s 循环占用）。
- **[R3] LangChain 包类型质量可能破 mypy 严格门禁** → 允许 `integrations/` 局部豁免（逐行 `# type: ignore[code]` + 注释理由），禁止文件级/包级一揽子豁免。
- **[R4] LangChain 1.x API 演进** → 暴露面收敛在 `integrations/` 五个文件内，升级影响可控；依赖版本 pin 到 minor。
- **[R5] 观测开启时业务数据（问题、召回原文）出网** → 默认关闭 + endpoint 可配置（内网自托管）+ 企业部署文档明示数据流向；生产开不开、指哪里由部署方决策，架构不绑定。
- **[R6]（任务 5.4 实测新增）langchain-milvus 0.4.0 的自动建表路径不可依赖**：auto-create 不应用 `enable_dynamic_field` 构造参数，且以首个 batch 的 metadata 键推导 collection 字段（键不一致即 `InsertUnexpectedField`/missed-field）。**决策：collection schema 由 ingest change 显式创建**（可选字段 `nullable=True`：`parent_id` / `page_idx` / `bbox`），`build_vectorstore` 固定 `enable_dynamic_field=False` 假定连接已存在的 collection；检索参数名为 `expr`（非 `filter`），已封装在 retriever 内部。

## Migration Plan

纯新增，无存量迁移：依赖加入 `pyproject.toml` → `uv sync`；新环境变量全部可选有默认值（缺省观测关闭，scaffold 配置规约天然覆盖）；不触碰既有表结构与 API。回滚 = 移除 integrations 新增文件与依赖（本 change 未接线任何业务端点，回滚零业务影响）。`openspec/project.md` 技术栈表在 archive 时补充依赖行。

## Open Questions

- partition_key spike 结论（R1）：若 expr-only 即满足延迟目标，则 KB 隔离是否仍声明使用 partition_key，留待后续 ingest capability 定稿时一并确认。
- 授权 TTL 缓存若未来开启，默认 TTL 值的最终取值（spec 已限 ≤5s 上限，具体值不影响契约）。

## Deferred / 后续 change 承接（code review 自检后登记）

0. **未授权内容的处置策略（已定：fail-closed + 专用安全异常）**：检索结果若出现授权集合外的 kb_id，说明过滤机制本身失效，本批结果整体不可信 → 中断本次检索，抛 `SecurityViolationError`（500 `security_violation`），越权 chunk_id 只进日志（带 request_id）供告警，**不进响应体**（统一错误信封会把 `details` 原样写出）。授权 TTL 缓存维持默认关闭（直查，撤销零延迟），10k 上限保留作运维杠杆。
1. **请求级 tracing 的运行时接线未随本 change 落地**：已交付决策纯函数 `resolve_request_tracing`，但真正的 `tracing_context` 包裹需要请求上下文与管理员调试标记通道，随 **QA 端点 change** 一并接线。spec 场景「进程关闭 + 请求标记开启 → 仅该请求产生 trace」目前只在决策层验证，**运行时验证归 QA change**。
2. **collection 度量方式契约（ingest 侧 MUST）**：`retriever` 取 `score = distance`（Milvus **COSINE** 度量直接返回余弦相似度，相同向量 = 1.0），`RetrievedChunk.score` 落在 [-1, 1] 契约内。ingest change 创建 collection 时 MUST 使用 COSINE 度量。（2026-09-14 修正：原假设 `score = 1 - distance` 与实际 Milvus 返回相反，已按真实集成验证改为 `score = distance`。）
3. **授权 TTL 缓存默认仍关闭**：本 change 只交付能力与有界实现（≤10k 条目 + TTL ≤5s），是否在生产开启由 QA change 依据实测延迟决定。
