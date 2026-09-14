## MODIFIED Requirements

### Requirement: 文档解析状态机推进并由入库任务反映进度

系统 SHALL 通过 Celery 任务驱动文档从上传直至具备可检索索引：非 `UPLOADED` 文档解析 MUST 短路返回（幂等）。解析成功 SHALL 先落盘 `content_list.json`（`artifact_path`）再置 `PARSED`。随后入库任务 SHALL 对 `PARSED` 文档执行切分：切分期间状态为 `CHUNKING`（切分中瞬态），切分完成后 `Chunk` 落库且状态回 `PARSED`（索引原料就绪）。再后续向量化任务 SHALL 将已切分文档推进到 `EMBEDDING`（向量化中瞬态），成功后置 `READY`（已可检索）。任一阶段失败 SHALL 将文档置 `FAILED` 并记录错误信息。同一 `IngestJob` 状态与 `stage` MUST 是入库进度与阶段的真相来源。

解析启动时文档状态 MUST 被置为 `PARSING`（不得跳过该状态）。

**瞬态状态 MUST 在长任务进入外部 I/O 之前对外可见**：`PARSING` / `CHUNKING` / `EMBEDDING` 三个进行中状态，连同对应的 `IngestJob`（`RUNNING` 与 `stage`）MUST 在该阶段开始调用外部依赖（文档解析服务、向量化模型、向量库）之前提交到业务数据库，使得并发的只读查询能够观测到进行中状态。瞬态状态与任务全程外部 I/O MUST NOT 处于同一未提交事务中；任务的最终结果（成功或失败）同样 MUST 提交。

#### Scenario: 解析成功

- **WHEN** 解析任务处理一篇 `UPLOADED` 文档且 MinerU 成功
- **THEN** 文档状态为 `PARSED`、`artifact_path` 指向产物，`IngestJob` 为 `SUCCESS`

#### Scenario: 解析失败

- **WHEN** 解析任务中 MinerU 返回失败或网络异常
- **THEN** 文档与 `IngestJob` 均为 `FAILED`，且 `error_message` / `error` 记录原因

#### Scenario: 切分落库后原料就绪

- **WHEN** 入库任务处理一篇 `PARSED` 文档且切分成功
- **THEN** 文档状态经 `CHUNKING` 回到 `PARSED`，其 `chunks` 已落库可查，`IngestJob` 反映切分阶段成功

#### Scenario: 一路推进到 READY

- **WHEN** 向量化任务处理一篇已切分的文档且编码、写入 Milvus 均成功
- **THEN** 文档状态经 `EMBEDDING` 最终为 `READY`，`IngestJob` 为 `SUCCESS` 且反映向量化阶段完成

#### Scenario: 切分失败留下可恢复状态

- **WHEN** 入库任务中切分失败
- **THEN** 文档置 `FAILED` 且错误信息保留，不产出损坏的 `chunks`，修复后可重放

#### Scenario: 向量化失败留下可恢复状态

- **WHEN** 向量化阶段失败
- **THEN** 文档置 `FAILED` 且错误信息保留；已写入向量可辨识、可清理，重放后从向量化阶段如实恢复

#### Scenario: 重放幂等

- **WHEN** 入库任务再次处理一篇已切分（`PARSED` 且已有 `chunks`）或已 `READY` 的文档
- **THEN** 任务直接返回，不重复切分、编码或写入

#### Scenario: 进行中状态可被并发查询观测

- **WHEN** 一篇文档的解析（或切分、向量化）任务正在等待外部依赖返回，此时另一会话查询该文档
- **THEN** 查询到的状态为该阶段的进行中状态（`PARSING` / `CHUNKING` / `EMBEDDING`），且 `IngestJob` 为 `RUNNING` 并带有对应 `stage`

#### Scenario: 任务被中断后不留“永久进行中”状态

- **WHEN** 任务所在进程在外部 I/O 期间异常终止，文档停留在瞬态状态
- **THEN** 该文档仍可被重新驱动：任务入口的状态校验允许对瞬态文档按其阶段恢复或重新执行，不会因为状态非 `UPLOADED` / `PARSED` 而永久卡死
