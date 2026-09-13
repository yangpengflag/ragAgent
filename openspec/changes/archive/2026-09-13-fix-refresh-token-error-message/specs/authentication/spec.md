## MODIFIED Requirements

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

- **WHEN** 从白名单之外的来源发起刷新请求
- **THEN** 返回 403 `access_denied`

#### Scenario: 刷新失败文案指代刷新令牌

- **WHEN** 刷新因令牌缺失、签名非法、已被撤销、账号不可用或会话纪元落后而失败
- **THEN** 响应 `error_code` 为 `unauthorized`，且 `message` 指代刷新令牌无效或失效，不出现「用户名或密码错误」这类登录文案

#### Scenario: 刷新令牌过期仍用过期错误码

- **WHEN** 携带已过期的刷新令牌调用刷新接口
- **THEN** 返回 401 且 `error_code` 为 `token_expired`
