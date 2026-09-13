# Tasks: rag-orchestration-langchain

## 1. Spike（前置验证，结论回填 design.md）

- [x] 1.1 Spike：Milvus 2.5.10 Standalone 上验证 partition_key 字段与 `kb_id in [...]` expr 过滤的组合行为（创建含 partition_key 的临时 collection，写入多 kb 数据，验证 expr 过滤正确性与剪枝延迟）；结论记入 design.md R1
- [x] 1.2 Spike：验证 LangSmith SDK 在观测后端连接黑洞（不可达端点 + 防火墙超时）条件下是否阻塞调用线程；若存在同步阻塞路径，确定隔离方案（显式异步 handler）；结论记入 design.md R2

## 2. 依赖与配置

- [x] 2.1 `backend/pyproject.toml` 新增 `langchain-core`、`langchain-openai`、`langchain-milvus`、`langsmith`（minor 版本 pin），`uv sync` 落地；确认未引入 `langchain-community` / `langchain` 主包 / `langgraph`
- [x] 2.2 配置层新增观测相关可选配置项（`LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` / `LANGSMITH_ENDPOINT`），全部有默认值（缺省 = 关闭）；`.env.example` 补充注释说明；TDD：缺省启动成功且观测关闭、配置读取类型正确

## 3. 领域契约（纯函数层）

- [ ] 3.1 `domain/` 定义检索契约 dataclass（`RetrievedChunk`：chunk 标识、正文、kb_id、文档/页码定位元数据、得分），零框架依赖；TDD 单测覆盖字段构造与不变量

## 4. integrations 组件封装

- [x] 4.1 `integrations/llm.py`：DashScope OpenAI 兼容模式 ChatModel 工厂（base_url/api_key/model 可配置）；TDD：用 langchain-core FakeChatModel 验证工厂装配与配置注入
- [x] 4.2 `integrations/embeddings.py`：Embeddings 工厂（同一 compatible-mode 入口，1024 维模型可配置）；TDD：FakeEmbeddings 验证装配
- [x] 4.3 `integrations/vectorstore.py`：langchain-milvus 装配（database `ragagent`、collection 配置、 Milvus 不可用时启动不崩溃由健康检查承接）；TDD：配置注入与构造参数断言（不依赖真实 Milvus）
- [ ] 4.4 类型边界检查：确认 LangChain 类型不出现在 `domain/` 与 `services/`（ruff 自定义规则或 import 约定文档 + review 清单）

## 5. 权限过滤 Retriever

- [x] 5.1 授权解析服务（范围修订：`user_kb_grant` 表归 knowledge-base-crud change 所有，此处面向窄端口 `KbGrantReader` 实现）：默认直查不缓存（撤销即时生效）；可选 TTL 缓存（构造期强制 TTL ≤ 5s，spec 上限结构化）；读取失败 fail-closed（异常冒泡为 503，不降级为空授权静默放行）；TDD：新增/撤销授权即时反映、TTL 过期收敛、构造期 TTL 越界拒绝
- [x] 5.2 过滤表达式构造纯函数：授权集合 → Milvus expr（`kb_id in [...]`），含 partition_key 决策（按 spike 1.1 结论）；TDD：纯函数单测（空集合/单库/多库/表达式转义）
- [x] 5.3 `integrations/retriever.py`：自定义 Retriever——空授权集合短路返回空结果（不查向量库）；非空时携带 expr 执行检索并转换为 `RetrievedChunk`；TDD：mock vectorstore 验证短路、expr 透传、类型转换、未授权内容不可出现
- [x] 5.4 集成验证（可选真实 Milvus，标记为需中间件）：写入两个 kb 的样例向量，验证仅授权库内容可见（对应 spec "未授权库内容不可见" 场景）

## 6. 观测（LangSmith）开关与 fail-open

- [x] 6.1 `integrations/tracing.py`：进程级开关装配（env → callback 配置），endpoint 可配置；关闭态一并清除目标/凭证（任何路径都无法外发）；TDD：缺省关闭、配置齐全时开启、配置不全时 fail-safe 强制关闭
- [x] 6.2 请求级开关：决策纯函数 `resolve_request_tracing`（进程级为基线、请求级只做追加开启）；TDD：四种组合
- [x] 6.3 fail-open 验收测试：观测开启 + 后端黑洞/快速拒绝下，业务调用结果正确、无异常冒泡、主线程耗时无阻塞（对应 spec 两个 fail-open 场景）
- [x] 6.4 数据出网验收：关闭态与目标缺失态下断言环境无可用目标/凭证（不依赖 SDK 全局状态——langsmith pytest 插件会全局开启 tracing，该状态不可断言）

## 7. 问答链组装与 prompt 入仓

- [ ] 7.1 prompt 模板入仓：`domain/generation/`（或 services 层常量模块）定义仓库内模板常量，含版本注释；确认无运行时外部拉取路径
- [ ] 7.2 LCEL 问答链组装（services 层）：retriever → prompt → llm → parser，支持流式（astream）；引用脚注占位（[n] 标注逻辑归后续 QA change，此处仅透传 RetrievedChunk 元数据）；TDD：FakeChatModel/FakeEmbeddings + mock retriever 全链路单测
- [ ] 7.3 断网验收测试：除模型 API（Fake 替身）外无外网依赖，链路正常（对应 spec "无外网提示词服务时链路可用" 场景）

## 8. 质量门禁与收尾

- [x] 8.1 质量门禁（范围已定稿）：`uv run ruff check .` 零错误（scripts 存量错误顺手 `--fix`）+ `uv run mypy app` 零错误；tests/ 与 scripts/ 的 mypy 存量类型债**不在本 change 范围**，记为独立后续事项
- [x] 8.2 全量测试离线通过（无真实模型、无真实观测后端、中间件可缺省）；测试输出含用例统计
- [x] 8.3 回填 spike 结论至 design.md（R1/R2/R6），若结论影响 spec 契约则先修订 spec 再继续
- [x] 8.4 更新 `openspec/project.md`：技术栈表补充 LangChain/LangSmith 依赖行、架构分层说明 integrations 边界纪律（archive 流程内完成）

## Code Review 自检后追加（已修复）

- [x] R1-修复 expr 转义顺序：先转义反斜杠再转义引号（权限过滤表达式的注入面）
- [x] R2-修复 纵深防御：检索结果校验 kb_id ∈ 授权集合，未授权内容显式阻断（不依赖单一过滤机制）
- [x] R3-修复 缓存有界：TTL 缓存上限 MAX_CACHE_ENTRIES + 过期清理 + 淘汰最旧
- [x] R4-修复 元数据缺 chunk_id/document_id 报明确错误（替代 KeyError 500）
- [x] R5-决策一 未授权内容处置：新增 `SecurityViolationError`（500 + `security_violation`），整批中断；越权 chunk_id 仅进日志（响应体不含内部标识）
- [x] R6-决策二 授权缓存：维持默认关闭（直查）+ 10k 上限，不做变更
