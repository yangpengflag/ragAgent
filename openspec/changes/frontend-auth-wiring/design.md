## Context

动机见 `proposal.md`，需求契约见 `specs/frontend-shell/spec.md`。本文件只写「怎么做」。

**后端契约（由 `auth-and-users` 交付，本 change 只消费）**：

| 接口 | 请求 | 响应 / 副作用 |
|---|---|---|
| `POST /api/v1/auth/login` | `{username, password}`，携带凭据 | `{access_token, token_type, expires_in, user}`；`Set-Cookie` 下发刷新令牌（`HttpOnly`，`Path=/api/v1/auth/refresh`） |
| `POST /api/v1/auth/refresh` | 无请求体，仅靠 Cookie | `{access_token, token_type, expires_in, user}`；轮换刷新 Cookie |
| `POST /api/v1/auth/logout` | 无请求体，仅靠 Cookie | 撤销刷新令牌并清 Cookie，幂等 |
| `GET /api/v1/auth/me` | Bearer 访问令牌 | 当前账号 `{id, username, display_name, system_role}` |

错误信封为 `{request_id, error_code, message, details?}`；未认证 401 `unauthorized`、无权限 403 `access_denied`、凭据错误 401、限流 429 `rate_limited`。跨源凭据支持已由后端开启（`Access-Control-Allow-Credentials: true` + 回显来源）。

**前端现状（`frontend-shell` 已交付）**：

- `lib/api/client.ts` 已具备「401 → 刷新 → 重放一次 → 失败跳转登录」，且已处理「令牌已被其他请求刷新则直接重放」与「刷新失败通知幂等」
- `lib/api/session.ts` 提供 `setTokenRefresher` / `setAuthFailureHandler` / `setAccessToken` / `resetSession` —— 刷新实现是未接线的占位
- `AppLayout` 已把 `setAuthFailureHandler` 接到 `navigate("/login")`
- `/login` 是 `PlaceholderPage` 占位路由；路由表平铺，无公开/受保护之分
- `apiFetch` 目前不支持 `credentials` 选项（默认同源），跨源携带 Cookie 需要补

## Goals / Non-Goals

**Goals:**

- 让「会话」成为显式状态，而不是散落在请求副作用里
- 把既有刷新机制接线为真实行为，并用真实 HTTP 验证（而非只靠单测）
- 守卫行为可预测：未知态不渲染受保护内容、匿名态跳转且可回到原目标
- 登出路径在服务端失败时也能退出（不把用户困在界面里）

**Non-Goals:**

- 不引入状态管理框架之外的新依赖（沿用已有 Zustand + TanStack Query）
- 不做令牌持久化（`localStorage` / `sessionStorage` 一律不用）
- 不做权限驱动的 UI 显隐（`system_role` 仅用于展示与后续扩展）
- 不做账号管理界面

## Decisions

### F1. 会话引导用显式刷新，而非依赖 401 重放

**选择**：应用启动进入 `未知` 态 → 显式调用刷新接口 → 成功则拉取当前账号进入 `已登录`，失败进入 `匿名`。

**备选**：启动直接调 `GET /auth/me`，靠请求层的「401 → 刷新 → 重放」自动恢复。少写一个状态机，但未登录用户必然先吃一个 401 再跳转，且守卫在未知态下难以避免受保护内容闪现。

**理由**：spec 明确要求「恢复过程中不得渲染受保护内容」，显式状态机比复用副作用可控。

### F2. 访问令牌仅存内存

**选择**：访问令牌保存在模块级变量（由 `session.ts` 持有），不写 `localStorage` / `sessionStorage`；整页刷新后靠刷新 Cookie 重新换取。

**理由**：XSS 读不到内存变量，显著降低长期凭据被窃取的面。代价是整页刷新多一次刷新往返。

### F3. 守卫实现为包裹组件

**选择**：`RequireAuth` 包裹受保护路由——未知态渲染全屏加载、匿名态 `Navigate` 到 `/login` 并把当前地址放进 `state.from`，登录成功后跳回。

**备选**：在 `AppLayout` 内用 `useEffect` 检测并跳转——渲染与跳转分离，易出现"先看到内容再被弹走"。

### F4. 跨源凭据通过 `apiFetch` 的 `credentials` 选项显式声明

**选择**：给 `RequestOptions` 增加 `credentials?: RequestCredentials` 并透传给 `fetch`；只有 `login` / `refresh` / `logout` 这三个依赖 Cookie 的接口传 `credentials: "include"`，业务接口保持默认。

**理由**：登录与刷新必须让浏览器接受/发送跨源 Cookie；业务请求靠 Bearer，无需携带 Cookie（少一类凭证暴露面）。默认值不改，避免影响既有接口行为。

### F5. 刷新失败与登出的边界处理

**选择**：
- **刷新失败**：由既有机制负责——`refreshAccessToken` 返回 `null` → 客户端调用已幂等的 `notifyAuthFailure()` → 会话置为匿名并跳转登录页。
- **登出**：无论服务端登出接口成功与否，**本地会话必须先清空**（内存令牌、账号、路由跳转）；服务端失败只记录告警。

**理由**：登出是用户表达"我要离开"的意图，不能因为后端或网络问题把人困在界面里；而服务端撤销失败的影响面由刷新令牌的自然过期兜底。

### F6. 测试用「会话状态」断言，不模拟 Cookie 细节

**选择**：msw 提供 login / refresh / logout / me 四类 handler；断言围绕**会话状态与路由结果**（登录后进入应用、刷新失败后回登录页、登出后不携带旧令牌），不试图在 jsdom 里模拟真实 Cookie 行为。

**理由**：jsdom + msw 不执行浏览器 Cookie 语义，强行模拟只能验证"我们自己的假实现"；Cookie 是否真的流通属于真机联调（任务 5.x）的范畴。这与 `frontend-shell` 既有测试策略一致（HTTP 全拦截、不依赖后端）。

### F7. 路由表按公开 / 受保护分组

**选择**：路由表显式分为「公开」（`/login`）与「受保护」（其余，包在 `RequireAuth` 下），不再平铺。

**理由**：后续新增业务页面只需加在受保护组内，守卫与未来可能的角色校验都自然继承，避免"新页面忘了加守卫"。

## Risks / Trade-offs

- **首屏多一次刷新往返**（F2）→ 会话恢复期间的加载态由守卫统一承担；若体验要求更高，可在启动时并行预取首页数据（后续优化）
- **未知态的统一加载页可能造成视觉闪动** → 加载态用整屏骨架而非空白；错误时展示可重试入口
- **登出服务端失败时仍算登出**（F5）→ 服务端撤销失败的告警需可观测；刷新令牌自然过期是兜底
- **`credentials: "include"` 与后端 CORS 强耦合** → 后端一旦改回通配符来源，浏览器会直接阻断请求；已在 `auth-and-users` 任务 1.7/1.8 用测试锁定
- **jsdom 下无法验证真实 Cookie**（F6）→ Cookie 行为必须在真机联调中确认（任务 5.1–5.4），不可仅凭单测声称通过
- **测试中的 `act` / 路由告警** → 沿用 `frontend-shell` 的做法（显式 future flags、避免不必要的 `pointerEventsCheck` 放宽）

## Migration Plan

实现顺序（也是 tasks 的顺序）：

1. 会话状态 + 请求层 `credentials` 透传 + 真实刷新接线 + 启动引导
2. 登录页（四态）
3. 守卫、原目标回跳、外壳账号区与登出
4. 测试基建扩展与门禁
5. 真机联调（登录 → 整页刷新仍在线 → 停用后立即失效 → 登出后不可刷新）

**回滚**：撤销 `setTokenRefresher` 接线与路由分组即可回到占位状态；本 change 不引入数据或后端改动，无数据迁移。

## Open Questions

（无。）
