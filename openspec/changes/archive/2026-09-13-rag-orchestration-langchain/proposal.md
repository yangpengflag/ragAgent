# Proposal: rag-orchestration-langchain

## Why

RAG 链路（解析→切分→向量化→检索→生成）尚未动工，`backend/app/domain/` 与 `backend/app/integrations/` 均为空——现在引入编排框架是零迁移成本的最佳窗口期。若先手写 LLM/Embedding/VectorStore 直连代码再事后抽象，重构成本高一个数量级；同时企业场景下 RAG 链路黑盒需要可调试、可评测、可观测的基建，观测能力必须从第一天就以"可开关、非必需依赖"的形态存在，而不是事后补丁。

## What Changes

- **引入 LangChain 组件基座**（不引入框架全家桶）：
  - 新增依赖：`langchain-core`、`langchain-openai`（DashScope 走 OpenAI 兼容模式，chat 与 embeddings 同一入口）、`langchain-milvus`、`langsmith`
  - 明确排除：`langchain-community`（1.0 后冻结维护态，拒绝进依赖树）、`langchain` 主包（1.0 转向 Agent Runtime，本项目纯 RAG 不需要）、`langgraph`（无分支无循环无工具调用，YAGNI）
- **`integrations/` 集成边界规范化**：LangChain 组件（ChatModel / Embeddings / VectorStore / Retriever）封装在 `backend/app/integrations/` 下；LangChain 类型（`Document` / 消息类型等）不得越过 integrations 边界进入 `domain/` 或 `services/`；`domain/` 零框架依赖铁律不变
- **切分器不进 LangChain**：结构感知切分（spec L0–L5）保持 `domain/chunking/` 纯函数实现，LangChain 通用 splitter 不参与
- **权限过滤 Retriever 契约**：授权关系（user → 可访问 kb_id 集合）的真相源为业务 MySQL；Retriever 接受授权 kb_id 集合作为输入，过滤以 Milvus expr / partition_key 在向量库检索阶段完成，禁止"先检索后过滤"
- **LangSmith 观测开关**：
  - 进程级开关（环境变量 `LANGSMITH_TRACING` 等）+ 请求级开关（`tracing_context`），支持"特定调试会话开 trace、普通流量关闭"的策略
  - 观测为**非生产链路必需依赖**：trace 上报失败（断网、密钥失效、SaaS 不可达）MUST NOT 影响问答链路的正确性与延迟
- **prompt 模板入仓**：prompt 以代码常量/配置入仓并纳入版本管理与 review，不使用 LangSmith Hub 托管
- **golden QA 评测归属划分**：评测集与门禁脚本入仓（CI 可离线跑），LangSmith Datasets/Evaluation 仅作可视化与对比面板，不承担门禁职责

## Capabilities

### New Capabilities

- `rag-orchestration`: RAG 链路的编排基座——LangChain 组件集成边界与替换约定、观测（tracing）可开关与 fail-open 语义、带权限过滤的 Retriever 契约、prompt 与评测产物的归属约定

### Modified Capabilities

（无——横切面配置加载、健康检查、测试门禁等行为已被 `project-scaffold` 覆盖，本 change 的 LangSmith 配置项归入既有"配置集中加载"规约，不改变其要求）

## Impact

- **代码**：`backend/app/integrations/`（新增 `llm.py` / `embeddings.py` / `vectorstore.py` / `retriever.py` / `tracing.py`）、`backend/app/services/`（问答链组装，后续 QA change 消费）、`backend/pyproject.toml`（依赖）
- **依赖**：新增 4 个 Python 包；DashScope 经 OpenAI 兼容端点接入，不新增 DashScope 专用 SDK
- **配置**：新增 `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` 等可选环境变量（全部有默认值，缺省 = 观测关闭）
- **后续 change**：本 change 只建立基座与契约；QA 端点、ingest 管道、切分器实现、稀疏/重排（二期）由后续 change 消费此基座
- **文档**：`openspec/project.md` 技术栈表与架构分层在 archive 时同步更新（补充 LangChain 组件与 LangSmith 依赖行）
- **风险前置项（进入 tasks）**：① partition_key 与 `kb_id in [...]` expr 过滤的组合行为需 spike 实测（Milvus 2.5.10 Standalone）；② tracing 上报失败在网络黑洞条件下的非阻塞性需实测验收
