## Purpose

为整个后端提供统一的应用骨架与横切基础设施：环境准备、配置加载、请求追踪、结构化日志、统一错误信封、数据库会话与迁移、健康检查，以及测试与质量门禁。后续所有业务能力都建立在这套骨架之上，避免各自实现一套配置、日志与错误格式。

## ADDED Requirements

### Requirement: 配置集中加载且缺失必填项时启动失败

系统 SHALL 从环境变量（支持仓库根 `.env` 文件）加载全部配置，并以类型化的方式提供给应用使用。当必需配置缺失时，系统 MUST 在**应用启动阶段**（而非首次调用时）立即失败，并 MUST 在错误信息与日志中明确指出缺失的配置项名称。所有阈值类参数（超时、批量大小、检索条数）MUST 可配置，不得硬编码。

#### Scenario: 缺少数据库配置时启动失败

- **WHEN** 环境变量中未提供 `MYSQL_HOST` 而启动应用
- **THEN** 应用启动失败，不会进入可服务状态，且错误信息与日志中均包含 `MYSQL_HOST` 字样

#### Scenario: 配置读取类型正确

- **WHEN** 配置中存在数值型参数（如端口、超时秒数）且值为合法数字字符串
- **THEN** 应用读取到的值为对应的数值类型，而非字符串

#### Scenario: 可选配置有默认值

- **WHEN** 可选配置项（如健康检查超时）未提供
- **THEN** 应用使用内建默认值正常启动

#### Scenario: 密码类空串配置被归一化为未设置

- **WHEN** 密码或令牌类配置的值为空字符串
- **THEN** 应用按"未设置"处理，不会以空密码发起认证

### Requirement: 每个请求携带唯一 request_id

系统 SHALL 为每个进入的 HTTP 请求确定唯一 `request_id`：若请求头 `X-Request-ID`（大小写不敏感）已携带非空值则沿用，否则生成新的唯一值。该 `request_id` MUST 同时出现在：该请求产生的所有日志条目中、响应的 `X-Request-ID` 响应头中、以及响应体中（成功与错误响应均包含）。

#### Scenario: 自动生成 request_id

- **WHEN** 客户端发起一个未携带 `X-Request-ID` 的请求
- **THEN** 响应体与响应头中均包含一个非空且相同的 `request_id`，且该请求产生的日志条目携带同一个值

#### Scenario: 沿用上游 request_id

- **WHEN** 客户端在请求头中携带 `X-Request-ID: abc-123`
- **THEN** 响应体与响应头中的 `request_id` 均为 `abc-123`

#### Scenario: 大小写不敏感

- **WHEN** 客户端携带 `x-request-id: abc-123`（小写）
- **THEN** 系统同样沿用该值

### Requirement: 日志结构化且不含敏感信息

系统 SHALL 以结构化（JSON）格式输出日志，并 MUST 自动携带当前请求的 `request_id`（若处于请求上下文中）。系统 MUST NOT 记录密钥、访问令牌、用户密码或完整文档正文。

#### Scenario: 日志为结构化格式

- **WHEN** 应用处理一个请求并输出日志
- **THEN** 每条日志可被解析为 JSON，且包含时间戳、级别、消息与 `request_id` 字段

#### Scenario: 敏感字段不被记录

- **WHEN** 处理涉及访问令牌或密码的逻辑并输出日志
- **THEN** 日志中不出现令牌或密码原文

### Requirement: 错误响应使用统一信封

系统 SHALL 将所有错误响应统一为 `{ request_id, error_code, message, details? }` 结构。`error_code` MUST 为语义化的 snake_case 标识，供调用方进行条件分支；`message` MUST 为面向调用方的可读描述，且 MUST NOT 暴露内部堆栈或实现细节。

#### Scenario: 资源不存在

- **WHEN** 请求一个不存在的资源
- **THEN** 返回 404，响应体包含 `request_id`、`error_code` 为 `not_found`、以及可读的 `message`

#### Scenario: 参数校验失败

- **WHEN** 请求参数不满足校验规则
- **THEN** 返回 422，`error_code` 为 `validation_error`，且 `details` 中给出字段级错误信息

#### Scenario: 未处理异常

- **WHEN** 处理过程中抛出未预期的异常
- **THEN** 返回 500，`error_code` 为 `internal_error`，响应中不含堆栈信息，而完整堆栈仅记录到日志

### Requirement: 数据库会话按请求生命周期管理

系统 SHALL 为每个请求提供独立的数据库会话，并 MUST 在请求结束时释放该会话（无论成功或失败）。系统 SHALL 提供可重复执行的 schema 迁移机制，迁移 MUST 可回滚。

#### Scenario: 请求结束释放会话

- **WHEN** 一个请求完成处理（无论成功或抛异常）
- **THEN** 该请求使用的数据库会话被关闭，不会泄漏连接

#### Scenario: 迁移可重复执行且可回滚

- **WHEN** 在独立的测试库上连续两次执行"升级到最新"命令
- **THEN** 第二次为无操作，schema 保持一致
- **WHEN** 执行一次回滚命令
- **THEN** schema 回退到上一版本且过程无报错

### Requirement: 通用实体字段由基类统一提供

系统 SHALL 为业务表提供统一的公共字段：主键（UUID v7，时间有序）、创建时间、更新时间、软删标记。创建时间 MUST 不可更新；删除 MUST 为标记式（写入软删标记），不得物理删除行。

本 change 只提供字段定义与软删方法，**不提供全局查询过滤**——查询默认排除已软删记录的能力推迟到首个业务实体引入时实现。

#### Scenario: 公共字段自动填充

- **WHEN** 创建一个继承公共基类的模型实例并提交
- **THEN** 该实例自动获得非空主键、创建时间与更新时间，且软删标记为空

#### Scenario: 创建时间不可更新

- **WHEN** 更新一条已存在的记录并提交
- **THEN** 其创建时间与创建时保持一致，而更新时间被刷新为更晚的值

#### Scenario: 软删保留数据

- **WHEN** 对一条记录执行软删并提交
- **THEN** 该记录仍存在于表中，且其软删标记被写入非空值

### Requirement: 健康检查端点报告各依赖组件状态

系统 SHALL 提供健康检查端点 `GET /api/v1/health`，返回结构化结果，包含 `request_id`、整体状态与 `components` 明细。整体状态 MUST 取值为 `ok`（全部组件可用）或 `degraded`（存在不可用组件）。`components` 中每一项 MUST 至少包含该组件的 `status`（`ok` 或 `down`）与 `error`（不可用时给出原因，可用时为 null）。

系统 MUST 分别探测 MySQL、Redis、Milvus 的连通性。当某个依赖不可用时，端点 MUST 仍返回 HTTP 200，并在 `components` 中标注。探测 MUST 设置超时，不得因某个依赖无响应而长时间挂起。

#### Scenario: 全部依赖正常

- **WHEN** MySQL、Redis、Milvus 均可用时调用健康检查
- **THEN** 返回 200，整体状态为 `ok`，且 `components` 中三个组件的 `status` 均为 `ok`、`error` 为 null

#### Scenario: 单个依赖不可用

- **WHEN** Milvus 不可用时调用健康检查
- **THEN** 仍返回 200，整体状态为 `degraded`，`components` 中 Milvus 的 `status` 为 `down` 且 `error` 给出原因，其余组件为 `ok`

#### Scenario: 依赖无响应时不挂起

- **WHEN** 某个依赖在探测超时时间内未响应
- **THEN** 该组件被标记为 `down` 并附带超时原因，健康检查正常返回，不会无限等待

### Requirement: 测试与静态检查可一键执行

系统 SHALL 提供测试与静态检查的标准命令，并 MUST 在项目骨架完成后处于全部通过状态。测试 MUST NOT 依赖外部真实模型服务或产生真实费用，且 MUST NOT 依赖开发者本机的中间件是否运行（中间件相关行为通过可替换的测试替身验证）。

#### Scenario: 运行测试套件

- **WHEN** 在无网络、且本机中间件未运行的环境中执行测试命令
- **THEN** 测试套件运行完成且全部通过，输出中包含用例统计

#### Scenario: 运行静态检查

- **WHEN** 执行 lint 与类型检查命令
- **THEN** 两者均无错误输出
