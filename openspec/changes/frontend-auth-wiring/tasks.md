## 0. 前置门禁

- [x] 0.1 确认 `auth-and-users` 已实现：`POST /api/v1/auth/{login,refresh,logout}`、`GET /api/v1/auth/me` 可用，且跨源凭据（`Allow-Credentials` + 回显来源）已生效。未完成前跳过 §5（真机联调），§1–§4 可用 msw 独立推进（实测：预检返回 allow-credentials:true 且回显来源；me/refresh 无凭据 401；login 错凭据 401 unauthorized）

## 1. 会话状态与请求层接线

- [x] 1.1 红灯：写测试——会话状态机：初始为未知态；登录成功后为已登录并持有账号；登出后为匿名
- [x] 1.2 绿灯：实现会话 store（Zustand）+ 访问令牌仅存内存（不写 `localStorage` / `sessionStorage`）
- [x] 1.3 红灯：写测试——`login` / `refresh` / `logout` 以携带凭据的方式发送且请求体不含刷新令牌；**认证端点自身的 401 不触发刷新重放**（刷新返回 401 时不递归、不自等待）
- [x] 1.4 绿灯：给 `apiFetch` 增加 `credentials` 透传；`features/auth/api.ts` 声明四个接口（`login` / `refresh` / `logout` 以不注入令牌、不重放的方式发出）。实测：`RequestOptions extends RequestInit`，`credentials` 已随 `...rest` 透传，`client.ts` 无需改动
- [x] 1.5 红灯：写测试——刷新实现：成功时更新内存中的访问令牌并返回令牌；失败时返回 `null` 且不抛异常
- [x] 1.6 绿灯：实现刷新实现并接线 `setTokenRefresher`（注册点：`AppProviders` 渲染期注入——子组件 effect 早于父组件，放 effect 会有"首屏请求未注入"的窗口）
- [x] 1.7 红灯：写测试——启动引导四种情形：有效会话 → 已登录；刷新令牌无效 → 匿名且不渲染受保护内容；**服务不可用（非 401）→ 引导失败态且可重试**；刷新成功但当前账号查询 401 → 匿名
- [x] 1.8 绿灯：实现启动会话引导（`refresh → me` 两步；区分 401 与其它失败）。store 新增 `bootstrap_error` 态（"我没登录"与"服务挂了"必须可区分）
- [x] 1.9 红灯：写测试——刷新失败后会话状态为匿名，且后续业务请求不再携带旧访问令牌
- [x] 1.10 绿灯：把 `setAuthFailureHandler` 的注册从 `AppLayout` **上移到应用级**：新增 `AuthFailureBridge`（无路径布局路由，挂在路由表最外层，随应用存活）；`AppLayout` 移除注册与 `useNavigate` 依赖
- [x] 1.11 重构：划清 auth 的 api / store / 引导 三层职责边界，避免互相调用形成环（现状：api=端点声明、session-store=纯状态、bootstrap/token-refresher/auth-failure=编排，依赖单向无环）

## 2. 登录页

- [x] 2.1 红灯：写测试——五态：提交中禁止重复提交、凭据错误提示（不区分账号是否存在）、网络/服务端错误可重试、429 限流提示、成功进入应用
- [x] 2.2 绿灯：实现登录页与表单（用户名、密码、提交、加载与错误展示），`/login` 路由接到 `LoginPage`
- [x] 2.3 绿灯：对「响应体不可读」的失败形态做通用兜底（不依赖 `error_code`，覆盖后端 500 缺 CORS 头的情形）。新增 2 条用例：`HttpResponse.error()`（连接层失败）与 500 空响应体
- [x] 2.4 重构：抽出可复用的表单错误展示组件 `components/FormError.tsx`，登录页只做编排；错误文案映射收敛到 `features/auth/login-error.ts`

## 3. 守卫、原目标回跳与外壳账号区

- [x] 3.1 红灯：写测试——未登录访问受保护路由跳转登录页且不渲染该路由内容；`/login` 与系统状态页在未登录时可正常访问
- [x] 3.2 绿灯：实现 `RequireAuth` 守卫并按「公开 / 受保护」分组路由表（公开：`/login`、`/`；受保护：其余）。新增 `SessionBootstrap`（无路径布局路由，挂载时 `refresh → me` 恢复会话）
- [x] 3.3 红灯：写测试——未登录访问受保护路由后完成登录，自动回到原目标
- [x] 3.4 绿灯：实现原目标回跳（守卫写入 `state.from`，登录页消费）
- [x] 3.5 红灯：写测试——已登录时外壳展示当前账号；触发登出后回到登录页且不再携带旧访问令牌；**服务端登出失败时本地仍完成登出**
- [x] 3.6 绿灯：实现外壳账号区与登出（`performLogout`：本地会话先清，服务端失败只吞掉不阻断）
- [x] 3.7 重构：整理路由表结构与导航配置，使新增业务页面默认处于守卫之内（入口 `main.tsx` 的 `createBrowserRouter` 与测试用 `AppRoutes` 共用同一张 `routes`）
- [x] 3.8 验证：以**真实刷新实现**复验「401 → 刷新 → 重放一次」链路（刷新实现由 `AppProviders` 接线，不再注入假 refresher）

## 4. 测试基建与门禁

- [x] 4.1 扩展 msw handlers：登录成功 / 凭据错误 / 429、刷新成功 / 失效 / 503、登出 / 登出失败、当前账号、已登录会话组合；并把散落在各测试里的重复定义收敛到 `tests/msw/handlers.ts`（需要捕获请求细节的用例保留内联 handler）
- [x] 4.2 验证：`npm run test` 全绿，且**后端未启动**时同样通过（实测：8000 端口无监听，68 passed）
- [x] 4.3 验证：`npm run lint`、`npm run build`（含 `tsc --noEmit`）均无错误；React 告警**较基线无新增**（基线为既有问题，见 design「实现期决策」第 3 条）

## 5. 真机联调与收尾

- [x] 5.1 启动后端与前端，用初始管理员登录，确认进入应用并展示账号。真机实测：真实浏览器 http://localhost:5173/login 提交后进入 `/` 并展示 `admin`；控制台 error/warn/issue 均为 0（跨源凭据真实生效、无 CORS 报错）
- [x] 5.2 整页刷新，确认会话被自动恢复。真机实测：浏览器 reload 后仍在 `/` 且账号为 `admin`，未跳登录页
- [x] 5.3 停用当前账号后立即失效。真机实测：新建测试账号登录 → 管理员调 `users/{id}/deactivate` → 访问受保护路由 `/chat` 立即回到 `/login`（无 15 分钟令牌窗口）。注：`/` 与 `/login` 按 F7 为公开路由，停用在公开页不会自动跳登录，但账号区随即消失
- [x] 5.4 登出后访问受保护路由回到登录页；原刷新令牌再调刷新接口确认 401。真机实测：在 `/chat` 点击登出 → 落到 `/login`；curl 复用登出前的 Cookie 调 refresh → 401 `unauthorized`
- [x] 5.5 复查：错误提示与后端 `error_code` 一致（真机错误密码 → 提示"用户名或密码错误"且按钮仍可提交）；控制台无 error/warn；`localStorage` / `sessionStorage` 均为空、`document.cookie` 不含刷新令牌（HttpOnly 生效）
- [x] 5.6 复查 500 缺 CORS 头：后端 `UnexpectedErrorMiddleware` 注册在 `CORSMiddleware` **之前**，未处理异常转成普通 JSONResponse 后向外穿过 CORS 自动补头 —— 浏览器可读到 500 信封；前端另有"响应体不可读"兜底（500 空响应体 → 按状态码给文案，已单测覆盖）
- [x] 5.7 更新 `AGENTS.md` 与 `frontend/README.md`（会话与守卫约定），提交变更
