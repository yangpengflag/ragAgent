# Proposal: fix-refresh-token-error-message

## Why

真机联调（`frontend-auth-wiring` §5.4）发现：刷新令牌失效时，后端返回的 `message` 复用了登录失败文案「用户名或密码错误」。用户在刷新会话的场景下看到"用户名或密码错误"会被误导（他并没有提交用户名密码），排障也会朝错误方向查。`error_code` 仍是 `unauthorized`，因此客户端分支逻辑不受影响，只是文案指代错误。

## What Changes

- 刷新链路（缺令牌 / 签名非法 / `jti` 已撤销 / 账号不存在或未启用 / 会话纪元落后）改用专属文案「刷新令牌无效或已失效，请重新登录」
- 登录失败文案「用户名或密码错误」保持不变（该文案的"不区分账号是否存在"语义是刻意的）
- `error_code` 与状态码一律不变：仍是 401 `unauthorized`（过期仍为 `token_expired`），客户端无需改动

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `authentication`：刷新令牌失效类失败的 `message` 从登录文案改为刷新专属文案（行为契约：对外错误文案需指代正确的失败场景）

## Impact

- **代码**：`backend/app/services/auth_service.py`（刷新路径的 5 处 raise）
- **测试**：新增刷新文案断言；既有登录/刷新用例的 `error_code` 断言不变
- **兼容性**：`error_code` 与状态码不变，前端与 `scripts/e2e_flow.py` 均无需改动
- **非目标**：不新增错误码、不改刷新失败后的 Cookie 清除与 503 语义
