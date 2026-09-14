# documents Specification

## Purpose

定义文档上传与解析入库的前段：文档作为知识库内的数据单元被上传、落盘、经 MinerU 解析为 `content_list.json`，并以文档状态机与 `ingest_jobs` 进度持久化其生命周期，为后续切分与向量化提供稳定原料。

## ADDED Requirements

### Requirement: 文档归属知识库并可上传

用户 SHALL 能向某个知识库上传文档；文档 MUST 唯一归属于该知识库。上传时系统 MUST 校验格式白名单（`pdf` / `docx` / `md`）与文件大小限制：格式不支持返回 415 `unsupported_file_type`，超限返回 413 `file_too_large`。库内已存在活跃且成功解析的同哈希文档时 MUST 返回 409 `conflict`。

上传 MUST 要求用户对目标库持有 `EDITOR` 或 `KB_ADMIN` 角色；`VIEWER` 或无授权 MUST 返回 403 `access_denied`。知识库不存在或已软删 MUST 返回 404 `not_found`。

上传成功后文档状态为 `UPLOADED`，并返回文档信息。

#### Scenario: 成功上传

- **WHEN** 持有 `EDITOR` / `KB_ADMIN` 的用户向知识库上传一个白名单内、未超限、库内无重复哈希的文件
- **THEN** 返回 201，响应含 `document_id`、`filename`、`status=UPLOADED` 与创建时间

#### Scenario: 格式不支持

- **WHEN** 上传 `.exe` 等白名单外文件
- **THEN** 返回 415 且 `error_code` 为 `unsupported_file_type`

#### Scenario: 文件过大

- **WHEN** 上传超过 `UPLOAD_MAX_SIZE_MB` 的文件
- **THEN** 返回 413 且 `error_code` 为 `file_too_large`

#### Scenario: 库内重复

- **WHEN** 上传的 SHA-256 与库内已 `PARSED` 的活跃文档相同
- **THEN** 返回 409 且 `error_code` 为 `conflict`

#### Scenario: 权限不足

- **WHEN** `VIEWER` 或对该库无授权的用户调用上传
- **THEN** 返回 403 且 `error_code` 为 `access_denied`

### Requirement: 文档解析产出结构化原料

系统 SHALL 在文档上传后，经文件存储落盘、经 MinerU 云 API 解析，并将产物 `content_list.json` 落盘。该产物 MUST 是下游切分器的唯一原料。解析任务 MUST 以异步方式执行，并把状态持久化到 MySQL 作为真相来源。

文档状态在解析期间 MUST 从 `UPLOADED` 推进到 `PARSING`，成功后为 `PARSED`；失败时 MUST 为 `FAILED` 且保留错误信息。解析任务 MUST 幂等：对已 `PARSED` 的文档重放不产生副作用。

#### Scenario: 解析成功

- **WHEN** MinerU 返回成功任务并产出 `content_list.json`
- **THEN** 文档状态为 `PARSED`，产物已落盘，associated `ingest_job` 为 `SUCCESS`

#### Scenario: 解析失败

- **WHEN** MinerU 上报失败或上游不可用
- **THEN** 文档状态为 `FAILED`、`error_message` 记录原因，job 为 `FAILED`，不生成可消费的产物

#### Scenario: 解析重放幂等

- **WHEN** 对已 `PARSED` 的文档再次触发解析
- **THEN** 不重复调用 MinerU，文档状态不变

### Requirement: 入库进度以 ingest job 持久化

系统 SHALL 提供 `ingest_jobs` 记录一次文档入库任务，状态取值 `PENDING / RUNNING / SUCCESS / FAILED`，并记录进度与错误信息。该记录 MUST 以 MySQL 为真相来源。查询文档时可附带其当前 job 状态。

#### Scenario: 上传即建档

- **WHEN** 文档上传成功
- **THEN** 创建一条 `PENDING` 的 `ingest_job` 与其关联

#### Scenario: 解析推进进度

- **WHEN** 解析任务开始与结束
- **THEN** job 依次为 `RUNNING` 与 `SUCCESS` / `FAILED`，并记录错误（如有）

### Requirement: 文档列表、详情与软删

系统 SHALL 提供知识库内的文档列表、单文档详情与软删。列表与详情 MUST 校验请求者对库的可访问授权（任意角色）；软删 MUST 校验 `EDITOR` / `KB_ADMIN`。软删 MUST 为标记式删除，不物理删除行。已软删文档 MUST 不出现在列表中。

#### Scenario: 列出文档

- **WHEN** 持有该库任意授权角色的用户查询列表
- **THEN** 返回该库活跃文档（不含已软删），每项含状态与 job 进度

#### Scenario: 查看详情

- **WHEN** 用户查询某文档详情
- **THEN** 返回文件名、状态、大小、错误信息（如有）与 job 状态

#### Scenario: 软删文档

- **WHEN** 持 `EDITOR` / `KB_ADMIN` 的用户软删某文档
- **THEN** 返回成功，文档被标记删除且不再出现在列表