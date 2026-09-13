# authentication Specification

## Purpose

定义账号的登录与令牌机制：凭据换令牌、短时访问令牌的无状态校验、基于 `HttpOnly` Cookie 的刷新令牌与轮换撤销、凭据变更后的即时失效、登录失败限流，以及供所有受保护接口复用的鉴权依赖与审计留痕。

## Requirements

### Requirement: 登录签发访问令牌与刷新令牌

系统 SHALL 提供 `POST /api/v1/auth/login`，接受 `username` 与 `password`。凭据正确时 MUST 返回访问令牌与账号摘要，并通过 `HttpOnly` Cookie 下发刷新令牌。刷新令牌 MUST NOT 出现在响应体中，也 MUST NOT 能被前端脚本读取。

响应体字段名为：`request_id`、`access_token`、`token_type`（固定 `Bearer`）、`expires_in`（秒）、`user`（账号摘要 `{id, username, display_name, system_role}`）。

#### Scenario: 登录成功

- **WHEN** 用户名与密码正确且账号处于启用状态
- **THEN** 返回 200，响应体含 `access_token` / `token_type` / `expires_in` / `user` 与 `request_id`，并设置 `HttpOnly` 的刷新令牌 Cookie；响应体中不出现刷新令牌

#### Scenario: 凭据错误

- **WHEN** 密码错误或用户名不存在
- **THEN** 返回 401 且 `error_code` 为 `unauthorized`，两种情形的对外错误信息一致（不暴露账号是否存在）

#### Scenario: 响应不泄漏敏感信息

- **WHEN** 登录成功或失败
- **THEN** 响应体与 `Set-Cookie` 中均不出现密码或密码哈希

#### Scenario: 刷新令牌 Cookie 的作用范围

- **WHEN** 检查登录响应的 `Set-Cookie`
- **THEN** 该 Cookie 为 `HttpOnly`，其 `Path` 同时覆盖刷新与登出两个端点（`/api/v1/auth`），使登出请求也能携带它

### Requirement: 跨源携带凭据的支持

由于前端应用与后端分属不同源（开发期分别位于 5173 与 8000 端口），系统 SHALL 允许来自配置白名单来源的跨源请求携带凭据（Cookie），且 MUST NOT 以通配符来源配合凭据使用。

#### Scenario: 白名单来源的跨源凭据请求

- **WHEN** 浏览器从配置的允许来源发起携带凭据的跨源请求
- **THEN** 响应包含 `Access-Control-Allow-Credentials: true`，且 `Access-Control-Allow-Origin` 回显该来源（而非通配符）

#### Scenario: 非白名单来源

- **WHEN** 请求来源不在允许列表中
- **THEN** 响应不包含允许该来源的 CORS 头，浏览器侧无法携带凭据访问

### Requirement: 访问令牌自带身份与角色

访问令牌 MUST 为签名的短时效令牌（默认 15 分钟，可配置），载荷 MUST 包含账号标识、系统角色、`jti`、签发时间与过期时间。签名校验失败、格式非法或已过期的令牌 MUST 被拒绝。

#### Scenario: 有效令牌访问受保护接口

- **WHEN** 携带有效访问令牌调用受保护接口
- **THEN** 请求被放行，处理逻辑可获取当前账号身份

#### Scenario: 令牌缺失或格式非法

- **WHEN** 未携带令牌，或令牌不是可解析的令牌格式
- **THEN** 返回 401 且 `error_code` 为 `unauthorized`

#### Scenario: 令牌已过期

- **WHEN** 使用已过期的访问令牌调用受保护接口
- **THEN** 返回 401 且 `error_code` 为 `token_expired`（与"缺失/非法"区分，便于客户端识别为可刷新场景）

#### Scenario: 签名被篡改

- **WHEN** 修改令牌载荷或签名后调用受保护接口
- **THEN** 返回 401，且不泄露令牌内容

### Requirement: 令牌刷新

系统 SHALL 提供 `POST /api/v1/auth/refresh`，从 `HttpOnly` Cookie 读取刷新令牌并签发新的访问令牌。刷新令牌 MUST 只从 Cookie 读取——请求体或查询参数中出现的刷新令牌 MUST NOT 被采纳。刷新成功时 MUST 轮换刷新令牌，原刷新令牌随即失效。

刷新 MUST 同时校验：签名有效、未过期、`jti` 未被撤销、**账号当前存在且启用**、且令牌签发时间不早于该账号的会话纪元（见「凭据变更或停用即时失效」）。任一项不满足 MUST 返回 401 并清除刷新令牌 Cookie；其中**令牌已过期**返回 `token_expired`（与访问令牌的过期语义一致，便于客户端识别），其余情形返回 `unauthorized`。

刷新类失败的 `message` MUST 指代刷新令牌本身（如「刷新令牌无效或已失效，请重新登录」），MUST NOT 复用登录失败的文案——刷新场景不存在"用户名/密码"输入，复用会误导用户与排障。各失败分支 MUST 共用同一句文案：不向调用方区分"撤销 / 账号停用 / 纪元落后"等具体原因，诊断细节只进服务端日志。

响应体字段名为：`request_id`、`access_token`、`token_type`、`expires_in`（MUST NOT 返回 `user`——账号信息由 `GET /api/v1/auth/me` 提供）。

刷新请求 MUST 校验来源：当请求携带 `Origin`（缺失时取 `Referer`）且其不属于配置白名单时，MUST 返回 403 `access_denied`；两者均缺失时视为非浏览器客户端，放行交由刷新令牌校验决定结果。

#### Scenario: 有效刷新令牌换取新的访问令牌

- **WHEN** 携带有效刷新令牌 Cookie 调用刷新接口
- **THEN** 返回新的访问令牌与有效期，且刷新令牌 Cookie 被更新为新的值

#### Scenario: 轮换后旧刷新令牌失效

- **WHEN** 使用已被轮换替换掉的刷新令牌再次刷新
- **THEN** 返回 401

#### Scenario: 无刷新令牌

- **WHEN** 未携带刷新令牌 Cookie 调用刷新接口
- **THEN** 返回 401

#### Scenario: 请求体中的刷新令牌不被采纳

- **WHEN** 仅把刷新令牌放在请求体中（Cookie 缺失）调用刷新接口
- **THEN** 返回 401，说明刷新令牌只从 Cookie 读取

#### Scenario: 停用或软删账号不能刷新

- **WHEN** 账号被停用或被软删后，携带其此前签发的有效刷新令牌调用刷新接口
- **THEN** 返回 401，不下发新的访问令牌，并清除刷新令牌 Cookie

#### Scenario: 非法来源的刷新请求被拒

- **WHEN** 刷新请求携带的 `Origin`（或 `Referer`）不在配置的允许来源内
- **THEN** 返回 403 且 `error_code` 为 `access_denied`，且不下发新的访问令牌

#### Scenario: 刷新失败文案指代刷新令牌

- **WHEN** 刷新因令牌缺失、签名非法、已被撤销、账号不可用或会话纪元落后而失败
- **THEN** 响应 `error_code` 为 `unauthorized`，且 `message` 指代刷新令牌无效或失效，不出现「用户名或密码错误」这类登录文案

#### Scenario: 刷新令牌过期仍用过期错误码

- **WHEN** 携带已过期的刷新令牌调用刷新接口
- **THEN** 返回 401 且 `error_code` 为 `token_expired`

### Requirement: 凭据变更或停用即时失效

系统 SHALL 保证账号的凭据或状态发生变化后，其**此前签发的全部刷新令牌立即失效**：重置密码、停用账号、软删账号与修改系统角色 MUST 均使该账号的既有会话不可再续期。已签发的访问令牌最迟在其有效期内自然失效。

#### Scenario: 重置密码后既有会话不可续期

- **WHEN** 管理员重置了某账号的密码，随后使用该账号此前签发的刷新令牌调用刷新接口
- **THEN** 返回 401，无法换取新的访问令牌

#### Scenario: 停用后既有会话不可续期

- **WHEN** 账号被停用后，使用其此前签发的刷新令牌调用刷新接口
- **THEN** 返回 401

#### Scenario: 刷新成功后的新令牌不受影响

- **WHEN** 发生了上述变更之后，账号被重新启用并使用新密码登录
- **THEN** 登录成功，新签发的刷新令牌可正常刷新

### Requirement: 登出与刷新令牌撤销

系统 SHALL 提供 `POST /api/v1/auth/logout`，从 Cookie 读取当前刷新令牌并使其立即失效，同时清除 Cookie。撤销 MUST 在令牌自然过期前始终有效，且 MUST 幂等；撤销 MUST 只影响当前会话，不影响同账号在其他客户端的登录。

#### Scenario: 登出后刷新令牌失效

- **WHEN** 登出后使用原刷新令牌调用刷新接口
- **THEN** 返回 401

#### Scenario: 重复登出保持幂等

- **WHEN** 在没有有效刷新令牌的情况下再次调用登出
- **THEN** 返回成功（幂等），不产生错误

#### Scenario: 不影响其他客户端的会话

- **WHEN** 在同一账号于另一客户端已登录的情况下，在当前客户端登出
- **THEN** 另一客户端的刷新令牌仍然有效

### Requirement: 登录失败限流

系统 MUST 对登录失败实施限流：同一用户名与来源地址在窗口（默认 15 分钟）内失败次数达到阈值（默认 5 次）后，该组合的后续登录尝试 MUST 返回 429 且 `error_code` 为 `rate_limited`，即使凭据正确。窗口结束后 MUST 恢复；成功登录 MUST 清零该组合的失败计数。

来源地址 MUST 取对端连接地址（`request.client.host`），MUST NOT 信任可伪造的转发头（本期无反向代理）。

#### Scenario: 达到阈值后拒绝

- **WHEN** 同一用户名与来源地址在窗口内连续失败达到阈值后再尝试登录
- **THEN** 返回 429，且不再进行密码校验

#### Scenario: 窗口内凭据正确也被拒

- **WHEN** 处于限流窗口内且本次提交的凭据正确
- **THEN** 仍返回 429（防止以爆破方式验证凭据有效性）

#### Scenario: 成功登录清零计数

- **WHEN** 存在少量失败记录后成功登录
- **THEN** 该组合的失败计数被清零，后续失败重新从零累计

#### Scenario: 窗口结束后恢复

- **WHEN** 限流窗口已过
- **THEN** 该组合可再次正常尝试登录

#### Scenario: 伪造的转发头不能绕过限流

- **WHEN** 请求携带与实际来源不同的 `X-Forwarded-For`
- **THEN** 限流仍按真实对端地址计数，计数不因该头而变化

### Requirement: 撤销存储不可用时的安全取舍

系统 SHALL 在「撤销名单存储（Redis）不可用」时采取安全优先策略：刷新与登出 MUST 失败为 503 `upstream_unavailable` 且不下发新令牌；而登录失败限流的存储不可用时 MUST 放行登录（可用性优先），并记录告警日志。

#### Scenario: 撤销存储不可用时拒绝刷新

- **WHEN** 撤销名单存储不可用，客户端调用刷新
- **THEN** 返回 503 且 `error_code` 为 `upstream_unavailable`，不发放新令牌

#### Scenario: 撤销存储不可用时拒绝登出

- **WHEN** 撤销名单存储不可用，客户端调用登出
- **THEN** 返回 503，且客户端据此可提示"服务暂不可用，请稍后重试"

#### Scenario: 限流存储不可用时不阻断登录

- **WHEN** 限流存储不可用，用户以正确凭据登录
- **THEN** 登录成功，并产生一条告警日志说明限流未生效

### Requirement: 当前登录态查询

系统 SHALL 提供 `GET /api/v1/auth/me`，返回当前账号信息，响应体字段为 `request_id` 与 `user`（账号摘要 `{id, username, display_name, system_role}`），供客户端恢复会话与路由守卫使用。

#### Scenario: 查询当前账号

- **WHEN** 携带有效访问令牌调用该接口
- **THEN** 返回 200，`user` 含账号标识、用户名、显示名与系统角色，且不包含密码字段

#### Scenario: 令牌无效

- **WHEN** 令牌缺失、过期或无效
- **THEN** 返回 401 且 `error_code` 为 `unauthorized` 或 `token_expired`

### Requirement: 鉴权依赖区分未认证与权限不足

系统 SHALL 提供供所有受保护接口复用的鉴权依赖：解析当前账号、以及要求指定系统角色。未认证 MUST 返回 401；已认证但角色不足 MUST 返回 403 且 `error_code` 为 `access_denied`。

#### Scenario: 匿名访问受保护接口

- **WHEN** 未携带有效令牌访问受保护接口
- **THEN** 返回 401

#### Scenario: 角色不足

- **WHEN** 已认证但系统角色不满足接口要求
- **THEN** 返回 403（与 401 区分，便于前端区分「去登录」与「无权限」）

#### Scenario: 账号被停用后令牌立即失效

- **WHEN** 账号在被停用后仍持有效期内签发的访问令牌访问受保护接口
- **THEN** 返回 401（鉴权 MUST 校验账号当前状态，停用与软删立即生效）

### Requirement: 认证事件审计

系统 SHALL 对登录成功、登录失败、限流触发、刷新失败、登出与账号管理写操作输出结构化日志，包含 `request_id`、用户名或账号标识（若可得）、来源地址与结果。日志 MUST NOT 包含密码、密码哈希或令牌原文。

#### Scenario: 登录失败留痕且不含密码

- **WHEN** 一次登录因密码错误而失败
- **THEN** 产生一条含用户名与失败结果的结构化日志，且日志中不出现密码原文

#### Scenario: 创建或重置密码的日志不含密码

- **WHEN** 管理员创建账号或重置密码（成功或失败）
- **THEN** 该请求产生的结构化日志中不出现密码原文

#### Scenario: 登出留痕

- **WHEN** 调用登出
- **THEN** 产生一条含账号标识与结果的结构化日志，且日志中不出现刷新令牌原文
