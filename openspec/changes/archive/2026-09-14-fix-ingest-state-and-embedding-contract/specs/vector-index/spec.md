## MODIFIED Requirements

### Requirement: 向量化并落库

系统 SHALL 把 `is_recallable` 的 child chunk 进行向量化（DashScope `qwen3.7-text-embedding`，1024 维，入库 `text_type=document`）并写入 Milvus，同时维持其 MySQL `chunk` 元数据一致。面向检索的下推过滤字段 MUST 全部落在标量列上。

入库阶段的编码请求 MUST 显式携带 `text_type=document` 语义（该模型为非对称检索模型：入库侧与查询侧使用不同的文本类型标记）。**该取值 MUST NOT 依赖服务端默认值**：服务端在未声明时的默认行为与文档侧语义不一致，依赖默认会导致入库内容被按查询侧编码，且不会产生任何报错。入库侧与查询侧的类型标记 MUST 同源于一处定义，不得在调用点各自硬编码字符串。查询侧 MUST 使用 `text_type=query`；查询侧的实际接线归问答（`qa`）能力负责，本文仅界定两侧取值不得混用。

#### Scenario: 成功落库

- **WHEN** 一批 child chunk 完成向量化并写入
- **THEN** 每条 chunk 在 Milvus 中可按 `chunk_id` 检索到，与其 MySQL 元数据一致

#### Scenario: 检索过滤字段可下推

- **WHEN** 对 collection 发起带 `kb_id` 的检索查询
- **THEN** 命中范围严格限定在该库

#### Scenario: 入库编码使用 document 语义

- **WHEN** 入库任务对 child chunk 发起编码请求
- **THEN** 请求以 `document` 类型标记发出，不以查询类型标记发出

#### Scenario: 查询编码使用 query 语义

- **WHEN** 检索侧对用户问题发起编码请求
- **THEN** 请求以 `query` 类型标记发出，与入库侧的类型标记不同且二者取自同一处定义
