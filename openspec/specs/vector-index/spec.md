# vector-index Specification

## Purpose
把切分产物 `Chunk`（child）向量化后写入 Milvus，形成可检索的向量索引：显式定义 collection schema 与 KB 隔离、批量幂等可重放落库、软删时同步清理向量，并驱动文档状态机推进到 `READY`。
## Requirements
### Requirement: 索引目标与向量库隔离

系统 SHALL 在 Milvus 中以显式定义的方式创建 collection，而非依赖框架自动建表。collection 主键 MUST 复用 chunk 的 UUID；`kb_id` MUST 作为 partition key 实现知识库级隔离剪枝；同一 collection 内 MUST NOT 混用不同向量维度或模型。

#### Scenario: 显式建 collection

- **WHEN** 首次向某 Milvus collection 写入 chunk
- **THEN** collection 已按约定 schema 显式创建，字段（主键 `chunk_id`、正文 `content`、向量 `vector`、分区键 `kb_id`）齐备且 `auto_id=False`

#### Scenario: 禁止混维度

- **WHEN** 尝试把与 collection 声明的 `embed_dim` / 模型不一致的向量写入
- **THEN** 该写入被拒绝并报告错误，不产生部分写入

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

### Requirement: 向量化状态机推进与失败补偿

系统 SHALL 通过 Celery 任务把已切分（`PARSED` 且含 chunks）的文档推进到 `READY`。向量化期间文档状态为 `EMBEDDING`（进行中瞬态），完成置 `READY`。文档在未达就绪原料状态时 MUST 短路返回（幂等，状态即重放护栏）。失败 SHALL 置 `FAILED` 并保留原因；已写入向量可辨识、可被清理，重放从该阶段如实恢复；重放 MUST 先清同文档旧向量再写入，不产生重复存活向量。

#### Scenario: 一路推进到 READY

- **WHEN** 向量化任务处理一篇已切分的文档且各步成功
- **THEN** 文档状态经 `EMBEDDING` 最终为 `READY`，`IngestJob` 为 `SUCCESS` 且 `stage` 反映完成

#### Scenario: 重放幂等

- **WHEN** 向量化任务再次处理一篇已 `READY` / 进行中的文档
- **THEN** 不重复编码与写入，不产生重复向量，文档状态不变

#### Scenario: 失败可恢复

- **WHEN** 向量化阶段失败
- **THEN** 文档状态为 `FAILED` 且保留失败原因；已写入向量可被清理，修复重放后从该阶段如实恢复

### Requirement: 软删文档同步清理索引

系统 SHALL 在软删文档时，同步删除该文档全部 chunk 的 Milvus 向量并软删对应的 MySQL chunk 记录，保证不再被检索。已软删文档的 chunk MUST NOT 出现在检索结果中。清理 MUST 幂等。

#### Scenario: 软删即不可检索

- **WHEN** 软删一篇已 `READY` 的文档
- **THEN** 该文档所有 chunk 向量从 Milvus 移除、MySQL chunk 被标记删除，后续检索不含其内容

#### Scenario: 重复软删与清理幂等

- **WHEN** 对已软删文档再次软删或清理
- **THEN** 操作幂等成功，不重复报错、不产生副作用

