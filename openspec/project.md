# Project Spec

> 项目级根 spec。所有 `specs/` 与 `changes/` 都建立在本文件描述的上下文之上。

## 项目名称

**EKB — 企业知识库与智能问答系统**（Enterprise Knowledge Base）

> ⚠️ 产品名待最终确认。**资源命名前缀统一为 `ragagent`**：MySQL 库 `ragagent` / `ragagent_test`、Milvus database `ragagent`、对象存储 bucket `ragagent`。改名成本为全局字符串替换，低。

## 愿景

> 让企业的制度、流程、技术文档变成"能问得动"的知识资产。

企业内大量知识沉淀在 PDF / Word / Markdown 里：制度办法、操作手册、技术规范、产品文档。检索靠 Ctrl+F，新人上手靠问人。

EKB 把这些文档解析、切分、向量化后建成可检索的知识库，让用户用自然语言提问，得到**有出处、可溯源、不编造**的答案。

## 范围（in scope）

- **多知识库（Knowledge Base）**：企业内部按部门/主题/项目建库，库与库之间数据与检索隔离。
- **用户与权限**：本地账号 + JWT 鉴权；**两层角色**——系统级 `ADMIN` / `MEMBER`（本期落地），库级 `KB_ADMIN` / `EDITOR` / `VIEWER`（随知识库能力落地）；库级 ACL；权限下推至向量检索。
- **文档管理**：上传 PDF / Word / Markdown；文件哈希去重；解析状态机；失败重试；删除同步清理索引。
- **文档解析（MinerU）**：提取文本、表格、代码、公式（LaTeX）、图片与图注；输出 `content_list.json` 作为下游唯一原料。解析后端可插拔（云 API / 本地服务）。
- **文本切分**：结构感知 + 动态长度 + 上下文增强 + 父子块；重叠缓冲作为可开关的兜底策略。
- **向量化与索引**：DashScope `qwen3.7-text-embedding`（1024 维）；Milvus 持久化；批量、幂等、可重放、失败补偿。
- **检索与问答**：向量召回（+ 稀疏/重排，开关控制）；`qwen-plus` 生成；SSE 流式；答案带引用脚注，可跳转原文并高亮定位。
- **引用溯源**：答案脚注 → 原始文档片段 → 页码/区域高亮。
- **检索评测**：golden QA 集 + 召回评测脚本，作为一切检索优化的前置门禁。
- **Web 管理端**：上传区、文档列表（状态机）、知识库管理、成员与授权、问答界面、检索调试台。

## 非目标（out of scope）

- **多租户 / SaaS 化**：本期面向单企业部署，不做 Tenant 维度隔离。
- **文档级 / 标签级 ACL**：仅做知识库级授权。
- **企业账号体系对接**：不做 LDAP / OAuth2 / SSO 实装（仅预留 AuthProvider 抽象）。
- **实时协作编辑**：不做在线编辑、版本对比、协同批注。
- **爬虫 / 外部数据源接入**：只支持人工上传文档，不做网站爬取、IM 归档、数据库同步。
- **多模态问答**：一期不把图片内容本身向量化（图注入索引，原图仅落盘供查看）。
- **移动端 App**：仅响应式 Web。
- **Agent / 工具调用**：本期为纯 RAG 问答，不给模型挂载业务工具。

## 关键术语

| 术语 | 含义 |
|---|---|
| Knowledge Base (KB) | 知识库，权限与检索的隔离单元。记录其 `embedding_model` / `embed_dim` / 切分配置 |
| Document | 上传的原始文档，唯一归属于一个 KB。状态机：`UPLOADED → PARSING → PARSED ⇄ CHUNKING → PARSED → EMBEDDING → READY / FAILED`。`PARSED` 复用为"解析 + 切分完成、索引原料就绪"，切分期为 `PARSED → CHUNKING → PARSED` 的转瞬态 |
| Block | MinerU `content_list.json` 中的一个内容块（`title`/`text`/`list`/`table`/`code`/`image`/`interline_equation`），携带 `text_level` / `page_idx` / `bbox` |
| Chunk | 切分后的检索单元。**Child chunk** 入向量库供召回，**Parent chunk** 仅存 MySQL 供生成 |
| Section Path | 章节面包屑，如 `第3章 费用管理 › 3.1 差旅费`，注入每个 chunk 前缀 |
| Contextual Prefix | （可选）由 LLM 为 chunk 生成的 50–100 token 语义定位前缀，替代/加强机械面包屑 |
| Ingest Job | 一次完整的入库任务（解析→切分→向量化→写入），由 Celery 异步执行，可重试 |
| Citation | 答案中的引用脚注，指向具体 chunk，可跳转原文并按 `page_idx`/`bbox` 高亮 |
| Golden QA | 评测集：问题 → 期望命中的文档/chunk。用于量化召回率，是开启任何检索优化的前置条件 |
| Capability Spec | OpenSpec 体系中一个独立能力单元的规格文档，对应 `openspec/specs/<capability>/spec.md` |

## 技术栈

前后端分离。Python 为后端主语言，React SPA 为前端。

| 维度 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.12 | 由 `uv` 管理；本机既有 3.10.0rc2 不可用（MinerU Windows 要求 3.10–3.12 正式版） |
| 后端框架 | FastAPI | 异步；原生 OpenAPI |
| ORM / 迁移 | SQLAlchemy 2.0 + Alembic | 迁移必须入仓 |
| 数据校验 | Pydantic v2 | 请求/响应 Schema 唯一来源 |
| 认证与令牌 | PyJWT + pwdlib[argon2] | 访问令牌 15 分钟（走响应体）/ 刷新令牌 7 天（走 `HttpOnly` Cookie）；密码哈希用 Argon2id。**不选** `python-jose`（≤3.3.0 有 CVE-2024-33663 / 33664）与 `passlib`（1.7.4 停更于 2020 年） |
| 任务队列 | Celery 5 + Redis | 解析/向量化等长任务 |
| 后端测试 | pytest + pytest-asyncio | 领域层纯函数单测为主 |
| 代码质量 | ruff + mypy | CI 门禁 |
| 关系库 | MySQL 8 | 元数据 + chunk 正文 |
| 缓存 / 队列 | Redis | broker + 缓存 + 限流 |
| 向量库 | Milvus 2.5.10 Standalone | 本地 Docker；**项目级用 database 隔离**（`ragagent`），**KB 级用 partition_key 隔离** |
| 文档解析 | MinerU | 默认云 API v4（`model_version=vlm`）；可切本地 `mineru-api`。两者输出均为 `content_list.json` |
| 生成模型 | DashScope `qwen-plus` | OpenAI 兼容模式 |
| 向量模型 | DashScope `qwen3.7-text-embedding` | **1024 维**；批量 20 条/次；单行 128k token。入库 `text_type=document`，查询 `text_type=query` |
| RAG 编排 | LangChain 组件（`langchain-core` / `langchain-openai` / `langchain-milvus`） | 仅用于组件抽象与链路编排；**不引入** `langchain-community`（1.0 后冻结）、`langchain` 主包与 LangGraph（纯 RAG 无 Agent 需求）。DashScope 经 OpenAI 兼容端点接入，不装 DashScope SDK |
| 链路观测 | LangSmith（可开关） | **非生产链路必需依赖**：默认关闭；上报失败 fail-open；上报目标 `LANGSMITH_ENDPOINT` 可配置（支持自托管，满足企业数据流向要求） |
| 重排模型 | DashScope `gte-rerank-v2` | 二期，开关控制 |
| 前端框架 | React 18 + Vite + TypeScript | 纯 SPA，无 BFF、无 SSR |
| 前端样式 | Tailwind CSS 4 + shadcn/ui (base-nova / neutral) + lucide-react | 沿用工作区既有样式规约 |
| 前端数据层 | TanStack Query + Zustand | 服务端状态 / 本地 UI 状态 |
| 前端测试 | Vitest + @testing-library/react + jsdom | |
| 文件存储 | 本地文件系统 | 抽象 `FileStorage` 接口，可切 MinIO；原始文件与解析产物均落盘 |
| 环境变量 | 根目录 `.env`（不入仓），`.env.example` 入仓 | |

### 端口约定

| 服务 | 端口 |
|---|---|
| FastAPI | 8000 |
| Frontend (Vite dev) | 5173 |
| MySQL | 3306 |
| Redis | 6379 |
| Milvus | 19530（HTTP 健康检查 9091） |
| MinerU 本地服务（若启用） | 8001 |

## 架构分层

```
backend/app/
├─ api/v1/            FastAPI 路由（薄：参数校验 + 调用 service）
├─ domain/            ★ 纯领域层：零 I/O、零框架依赖
│   ├─ chunking/      结构树构建 / 动态打包 / 上下文注入 / overlap
│   ├─ retrieval/     召回 / 融合 / 重排
│   └─ generation/    prompt 组装 / 引用标注
├─ services/          编排层：事务、状态机、跨组件协调
├─ integrations/      外部依赖适配：mineru / milvus / redis / storage / llm / embeddings / vectorstore / retriever / tracing / qa_chain

**集成边界纪律**（MUST）：LangChain / LangSmith 类型（`Document`、消息类型、Runnable 等）**不得越过 `integrations/`** 进入 `domain/` 或 `services/`——类型转换只在 integrations 内完成，由 `tests/test_import_boundaries.py` 守卫。
`domain/` 保留检索/切分/生成的纯函数与数据契约（`RetrievedChunk`、prompt 模板）；LangChain 的价值限定为「组件实现 + 链路编排 + 观测」，切分器等差异化资产不进框架。
├─ models/            SQLAlchemy 模型
├─ schemas/           Pydantic Schema
└─ tasks/             Celery 任务
```

**铁律**：`domain/` 不 import FastAPI / SQLAlchemy / SDK。切分器是纯函数（输入 `list[Block]` → 输出 `list[Chunk]`），单测毫秒级，是全仓 TDD 的主战场。

### 前端分层

```
frontend/src/
├─ app/                 路由表 + 布局壳 + 路由守卫
├─ features/<domain>/   按业务域组织：components/ hooks/ api.ts
├─ components/ui/       shadcn/ui 基础组件（不手改）
├─ components/          跨域共享组件
├─ lib/                 api client / utils / constants
└─ types/               共享类型
```

**目录约定（MUST）**：后端代码一律在 `backend/`，前端代码一律在 `frontend/`，仓库根不放源码。

## 已定稿的核心设计

### 切分策略

分层，逐层可开关：

| 层 | 内容 | 状态 |
|---|---|---|
| L0 | MinerU `content_list.json` 解析为 `list[Block]` | 必做 |
| L1 | 按 `text_level` 还原章节树，产出 breadcrumb | 必做 |
| L2 | table / code / equation 原子化（超限按行组/函数边界拆，表格重复表头） | 必做 |
| L3 | 按块类型动态 target token 贪心打包，不跨父节点 | 必做 |
| L4a | 结构面包屑注入 chunk 前缀 | 必做，零成本 |
| L4b | Contextual Retrieval（LLM 生成语义前缀） | 开关，需评测验证 |
| L4c | 父子块 small-to-big（子块入向量库，父块供生成） | 默认开 |
| L5 | 重叠缓冲 | **默认关**，仅作评测对照组；ratio 0.1、完整句为单位、不跨标题、表格代码不参与 |

块类型档位：

| 类型 | target tok | max tok | 备注 |
|---|---|---|---|
| text | 512 | 768 | 段落→句子→子句递归降级 |
| table | 1024 | 2048 | **双表示**：口语化摘要供检索 + 原文 Markdown 供生成 |
| code | 768 | 1024 | 按函数/类边界 |
| list | 512 | 768 | 按 item 打包 |
| equation | 256 | 512 | 保留 LaTeX 原文 |

token 计数用 `tiktoken(cl100k_base)` 代理估计 × 1.15 安全系数，封装为可插拔接口。

> **Late Chunking 当前不可行**：DashScope API 不暴露 token 级 embedding。记录为未来可选项（需本地部署开源 embedding 模型）。

### 检索策略

```
query → embedding(text_type=query)
      → Milvus 向量召回（filter: kb_id in 授权库；partition_key=kb_id）
      → [可选] 稀疏/关键词腿融合（RRF）
      → [可选] gte-rerank-v2 重排  top-50 → top-5
      → 回 parent chunk
      → qwen-plus 生成 + [n] 引用脚注
      → SSE 流式
```

**一期默认：dense-only，不加稀疏、不加重排。** 表结构与接口预留扩展位。启用任何优化前，必须已有 golden QA 集与评测脚本。

### 多知识库与权限

- **系统级角色**（账号维度）：`ADMIN` / `MEMBER`。`ADMIN` 可管理账号与全局配置；`MEMBER` 仅能访问被授权的知识库资源。
- **库级角色**（授权维度，随知识库能力引入）：`KB_ADMIN`（管本库文档与授权）/ `EDITOR`（上传与重建索引）/ `VIEWER`（仅检索问答）
- 授权表：`user_kb_grant(user_id, kb_id, role)`，库级粒度
- **权限下推**：Milvus 检索带 `kb_id` 过滤；禁止"先检索再过滤"
- **二次鉴权**：引用溯源返回 chunk 原文前再次校验权限
- **删除一致性**：文档删除必须同步清理 Milvus 向量；提供对账任务扫孤儿
- **向量库约束**：同一 collection 内禁止混 `embed_dim` / 混模型；换模型须整库重建或新 collection 双写切换

## 本机环境现状（2026-09-12 实测）

| 项 | 状态 |
|---|---|
| Python | ⚠️ 3.10.0rc2（不可用）→ 由 uv 装 3.12 |
| uv | 0.9.20 ✅ |
| 内存 | 15.7 GB（紧张；MinerU 与重负载不可叠加） |
| GPU | ❌ 无（本地 MinerU 只能用 `pipeline` 后端，精度 86.5） |
| Docker | Desktop 已装，内存限额 ~7.6 GB |
| MySQL | ✅ `mysql8` 服务运行中（3306） |
| Redis | ✅ 容器运行中（6379） |
| Milvus | ✅ `D:\docker-milvus` compose（etcd + minio + standalone v2.5.10），database 隔离复用 |
| Git | 父仓无 `.git`，待初始化 |

> 已知坑：`milvus-standalone` 容器可能被"孤儿化"（不在任何网络），启动时 panic `failed to create etcd client`。此时 `docker compose up -d` 不生效，须 `docker compose up -d --force-recreate standalone`。

## 质量底线

- 所有改动走 TDD（RED → GREEN → REFACTOR）。
- 主分支测试始终绿灯；`ruff` + `mypy` 零错误。
- 公开 API 改动必须先有对应 spec 更新。
- 检索相关优化必须有 golden QA 评测数据支撑，否则不合并。
- 密钥一律走环境变量，禁止入仓。

## OpenSpec Conventions

### Capability 粒度

- **新增 capability**：change 名与该 capability 名一致（kebab-case）。
- **只修改既有 capability**：不强制同名（例如 `frontend-auth-wiring` 修改 `frontend-shell`），但 MUST 在 `design.md` 说明。
- **一个 change 引入多个 capability**：仅当它们是可独立演进的分层、且依赖关系明确时允许，并 MUST 在 `design.md` 说明为何不再拆（例如 `auth-and-users` 的 `identity` 与 `authentication`）。
- archive 时 `openspec/specs/<capability>/spec.md` 各归各位、零冲突。

### `openspec/notes/` 的角色

- 存放人类可读的工程 brief（结构化但非 OpenSpec schema 格式）。
- OpenSpec CLI 不扫 `notes/`，仅 `specs/` 与 `changes/` 进入工作流。
- 用途：propose 阶段作为 LLM 上下文；review 阶段作为团队对齐文档；不参与 archive 合入。

## 维护

本文件每次 `/archive` 时检查是否需要更新。重大变化在对应 change 的 `design.md` 中写理由。

### 变更记录

- **2026-09-12 项目定稿**：由 Wanderchina（Java Spring Boot + Next.js）整体重定向为企业知识库系统（Python FastAPI + React Vite）。确定技术栈、切分与检索策略、多知识库与权限模型、环境现状。旧项目遗留的 submodule 结构不再适用，改为单仓。
- **2026-09-13 引入 LangChain 编排基座**：change `rag-orchestration-langchain`。RAG 链路动工前定编排层：LangChain 组件收口在 `integrations/`（边界由测试守卫），切分器/契约/prompt 留在 `domain/`，LangSmith 观测默认关闭且 fail-open。两个 spike 结论：Milvus partition_key + expr 过滤组合正确且剪枝有效；LangSmith 上报在网络黑洞下主线程零阻塞。新增风险记录 R6：langchain-milvus 自动建表路径不可依赖，collection schema 归 ingest 侧显式创建。
