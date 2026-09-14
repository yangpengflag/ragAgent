# documents Specification

## MODIFIED Requirements

### Requirement: 文档解析状态机推进并由入库任务反映进度

系统 SHALL 通过 Celery 任务驱动文档从上传直至具备可检索索引：非 `UPLOADED` 文档解析 MUST 短路返回（幂等）。解析成功 SHALL 先落盘 `content_list.json`（`artifact_path`）再置 `PARSED`。随后入库任务 SHALL 对 `PARSED` 文档执行切分：切分期间状态为 `CHUNKING`（切分中瞬态），切分完成后 `Chunk` 落库且状态回 `PARSED`（索引原料就绪）。再后续向量化任务 SHALL 将已切分文档推进到 `EMBEDDING`（向量化中瞬态），成功后置 `READY`（已可检索）。任一阶段失败 SHALL 将文档置 `FAILED` 并记录错误信息。同一 `IngestJob` 状态与 `stage` MUST 是入库进度与阶段的真相来源。

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

### Requirement: 文档按知识库访问权限分层查询与软删

系统 SHALL 提供文档列表、详情与软删能力，均以知识库为作用域。列表/详情 MUST 校验用户"可访问该库"（任意授权角色）并附带文档状态与入库阶段；上传与软删 MUST 校验用户对该库持 `EDITOR` / `KB_ADMIN`（或系统 `ADMIN`），`VIEWER` MUST 返回 403 `access_denied`。软删 MUST 为标记式（`deleted_at`）且 MUST 同步软删该文档的 `chunks` 并尽力清理其向量索引，已软删文档 MUST NOT 出现在列表中。

#### Scenario: 列表按库过滤且排除软删

- **WHEN** 有可访问权限的用户查询某库文档列表
- **THEN** 返回该库全部未软删文档，携带文档状态、`job_status` 与入库阶段，不含其他库文档

#### Scenario: 只读成员可读不可删

- **WHEN** 对某库仅持 `VIEWER` 的用户读取列表或详情
- **THEN** 读取成功；尝试软删文档时返回 403 `access_denied`

#### Scenario: 详情与软删作用域校验

- **WHEN** 手动构造"其他库的文档 id"请求详情或软删
- **THEN** 返回 404 `not_found`

#### Scenario: 软删同步清 chunks

- **WHEN** 软删一篇已切分的文档
- **THEN** 文档被标记删除并从列表消失，其全部 `chunks` 亦被标记删除，不再参与后续消费

#### Scenario: 软删即不可检索

- **WHEN** 软删一篇已切分或已 `READY` 的文档
- **THEN** 文档被标记删除并从列表消失，其全部 `chunks` 被标记删除且向量索引被尽力清理，检索不再命中其内容