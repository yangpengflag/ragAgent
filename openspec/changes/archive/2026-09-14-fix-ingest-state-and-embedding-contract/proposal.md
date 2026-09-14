## Why

三个文档入库 change（`document-upload-and-parse` / `document-chunking` / `document-embedding-index`）归档后经 Spec 对账，发现两条 **MUST 级契约未落地**，且都已进入已推送的主 spec：

1. **入库向量实际按「查询」侧编码（已实测确认）**：`openspec/specs/vector-index/spec.md` 的「向量化并落库」要求「入库 `text_type=document`」，但 `integrations/embeddings.py` 未传该参数（全仓零命中）。2026-09-14 对生产模型 `qwen3.7-text-embedding` 的**兼容端点**实测：
   - 不传 `text_type` 与显式传 `text_type=query` 得到**完全相同**的向量；
   - 显式传 `text_type=document` 得到**不同**向量（两次调用稳定复现）；
   - 传非法值（`text_type=bogus-value-xyz`）返回 **HTTP 400 InvalidParameter**，证明该参数确实被服务端解析而非忽略。

   即：**兼容端点「不传」时的默认行为是 `query`，与官方原生 API 文档所称的默认值 `document` 相反**。后果是入库的文档块被按查询侧文本编码，非对称检索的区分**完全没有建立**，且后续 `qa` 侧再传 `query` 也无法纠正——这直接损失召回质量，也是 project 质量底线要求「检索优化必须有评测数据支撑」的前置项。
2. **入库瞬态状态不可观测**：`openspec/specs/documents/spec.md` 要求切分期间为 `CHUNKING`、向量化为 `EMBEDDING`（`PARSING` 见 Purpose 的状态机全序）。但实现里 `resolve_parse` **从未赋值 `PARSING`**（docstring 与实现不符），且 `PARSING/CHUNKING/EMBEDDING` 均与长达数十秒的外部 I/O 处于**同一未提交事务**中，`flush` 在 I/O 之后才发生——并发查询在 MySQL 里读不到任何进行中状态，前端只能观察到 `UPLOADED → PARSED → READY` 的跳变，与「文档生命周期可查询、可追踪」的目标及 spec 时序契约不符。

两条都是**行为与 spec 不一致**（非实现细节），故必须改 spec 与代码，而不是只改代码。

## What Changes

- **补入库向量化语义**：入库侧编码**显式**声明 `text_type=document`，并把「入库 / 查询」两侧的取值收敛为**同源定义与单一构造入口**；查询侧（`query`）的实际接线留给 `qa` change，本 change 只定义两侧取值与入库侧落地。
- **以测试锁定该语义**：新增断言「入库编码请求确实携带 `text_type=document`」，防止未来回归到依赖服务端默认值（默认值即 `query`，静默降级且无报错）。
- **令瞬态状态可观测**：解析/切分/向量化三段在进入长 I/O 前，把「瞬态状态 + `ingest_job` RUNNING」**提交到 MySQL**（明确的提交边界，而非依赖任务结束时的单次 flush），使并发只读查询能观察到进行中状态；补齐 `PARSING` 赋值。
- **修正文档与实现的偏差**：`resolve_parse` 的 docstring 状态机描述与实现对齐。
- **同步 spec**：`documents` 的状态机条款明确「瞬态状态必须在长任务开始前对外可见」；`vector-index` 的入库条款明确 `text_type` 的取值与两侧契约边界。

不改变的内容：状态机的状态集合与终态语义、Milvus collection schema、切分算法、HTTP 接口形态（响应字段与路由不变）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `documents`: 「文档解析状态机推进并由入库任务反映进度」——明确瞬态状态（`PARSING` / `CHUNKING` / `EMBEDDING`）必须在长任务进入外部 I/O 之前对外可见，且 `PARSING` 必须被实际赋值。
- `vector-index`: 「向量化并落库」——明确入库侧 `text_type=document`，并界定查询侧 `text_type=query` 归 `qa` change。

## Impact

- **代码**：
  - `backend/app/services/document_service.py`（`resolve_parse` 提交边界 + `PARSING` 赋值）
  - `backend/app/services/chunk_service.py`、`backend/app/services/index_service.py`（`CHUNKING` / `EMBEDDING` 提交边界）
  - `backend/app/integrations/embeddings.py`（`text_type` 入参入口）
  - `backend/app/tasks/ingest.py`（任务内会话/事务边界配合）
- **测试**：新增瞬态可观测性用例（并发只读会话可观测进行中状态）、`text_type` 透传用例；既有 `test_document_*` / `test_index_service` / `test_task_*` 需适配事务边界。
- **API**：无对外契约变更（响应字段、路由、错误码不变）；但「文档详情可观测进行中状态」是**可感知的行为改善**。
- **数据**：无迁移（状态枚举与表结构不变）。
- **依赖**：无新增（`text_type` 走现有 OpenAI 兼容客户端透传，如不可行则见 design 备选）。
- **风险**：提交边界增加会改变任务的原子性假设（例如「半途失败不留半套」），需在 design 中明确「状态已提交、业务数据未提交」的语义与失败补偿。
