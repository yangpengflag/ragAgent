## Why

`auth-and-users` 交付后端认证接口后，前端仍处于「无登录态」：`setTokenRefresher` 是未接线的占位、`/login` 只是占位页、没有会话状态与路由守卫。后果有两个：

1. 任何受保护接口一上线（例如知识库列表）就会被 401 挡死，前端无法进入业务开发；
2. `frontend-shell` 里已经建好的「401 刷新重放、刷新失败跳转登录」机制只能停留在单测里，**无法端到端验证**——而它恰恰是这个外壳里最需要被真实流量检验的部分。

因此需要一个专门的前端变更，把「会话」这条链路接线完成。与 `auth-and-users` 拆开，是为了让后者的评审聚焦在接口契约与安全语义上，不必同时评审 UI 状态机。

## What Changes

- 新增**会话状态机**：`未知 → 已登录 / 匿名`，访问令牌仅存内存（不落 `localStorage` / `sessionStorage`）
- **接线真实刷新**：把 `setTokenRefresher` 指向真实的刷新实现，替换现有占位；刷新请求以携带凭据的方式发送
- **会话引导**：应用启动时尝试用刷新令牌恢复会话；未知态不得渲染受保护内容
- **登录页**：用户名/密码表单 + 提交中 / 凭据错误 / 网络错误 / 成功四态；错误提示不区分账号是否存在
- **路由守卫**：未登录访问受保护路由跳转登录页并保留原目标，登录成功后回到原目标；登录页自身匿名可访问
- **外壳账号区**：展示当前账号并提供登出（登出清除本地会话、通知服务端撤销、回到登录页）
- **请求层小改**：`apiFetch` 支持透传 `credentials`，供登录 / 刷新 / 登出携带 Cookie
- **测试基建扩展**：msw 补齐登录、刷新、登出、当前账号四类 handler

**不在本 change 范围内**：
- 任何后端改动（接口、CORS 凭据支持均已由 `auth-and-users` 交付）
- 账号管理界面（创建用户、改角色、重置密码——走接口，UI 留给后续 change）
- 注册、找回密码、第三方登录
- 知识库级权限相关的 UI 显隐（随 `knowledge-base-crud` 引入）

## Capabilities

### New Capabilities

（无。本 change 不引入新的对外能力，只把既有能力接入前端。）

### Modified Capabilities

- `frontend-shell`：应用外壳从「无鉴权占位」变为「真实登录态」——API 客户端需求补充「刷新令牌只经 `HttpOnly` Cookie 传递、前端不持有刷新令牌」；新增会话引导、受保护路由守卫、登录页、账号展示与登出四条需求

## Impact

- **前端新增**：`src/features/auth/{api.ts,hooks,components}`、`src/features/auth/SessionBootstrap.tsx`、登录页、`src/app/RequireAuth.tsx`
- **前端修改**：`src/lib/api/client.ts`（`credentials` 透传）、`src/features/auth` 接线 `setTokenRefresher` / `setAccessToken`、`src/app/routes.tsx`（公开 / 受保护路由分组）、`src/app/AppLayout.tsx`（账号区与登出）、`tests/msw/handlers.ts`
- **依赖前置**：需要 `auth-and-users` 已实现（`POST /api/v1/auth/{login,refresh,logout}`、`GET /api/v1/auth/me`，以及跨源凭据支持）
- **对后端的依赖方式**：仅通过 `VITE_API_BASE_URL` 与既定接口契约；本 change **不改动后端代码**
- **回滚**：撤销路由分组与 `setTokenRefresher` 接线即可回到占位状态，不影响其他页面
