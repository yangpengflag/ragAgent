## Context

动机见 `proposal.md`，需求契约见 `specs/frontend-shell/spec.md`。本文件只写「怎么做」。

**后端契约（由 `auth-and-users` 交付，本 change 只消费；字段名已在该变更的 spec 中冻结）**：

| 接口 | 请求 | 响应 / 副作用 |
|---|---|---|
| `POST /api/v1/auth/login` | `{username, password}`，携带凭据 | `{request_id, access_token, token_type, expires_in, user}`；`Set-Cookie` 下发刷新令牌（`HttpOnly`，`Path=/api/v1/auth`，`SameSite=Lax`，`Secure` 由后端配置） |
| `POST /api/v1/auth/refresh` | 无请求体，仅靠 Cookie，携带凭据 | `{request_id, access_token, token_type, expires_in}`（**不含 `user`**，账号信息另调 `/me`）；轮换刷新 Cookie |
| `POST /api/v1/auth/logout` | 无请求体，仅靠 Cookie，携带凭据 | 撤销刷新令牌并清 Cookie，幂等 |
| `GET /api/v1/auth/me` | Bearer 访问令牌 | `{request_id, user: {id, username, display_name, system_role}}` |

`user` 摘要字段为 `{id, username, display_name, system_role}`。错误信封为 `{request_id, error_code, message, details?}`；错误码：未认证 401 `unauthorized`、过期 401 `token_expired`、无权限 403 `access_denied`、凭据错误 401 `unauthorized`、限流 429 `rate_limited`、撤销存储不可用 503 `upstream_unavailable`。

> 状态码 503 的处理：登出/刷新遇到 503 说明后端撤销能力暂不可用，前端按普通错误提示即可（不要误判为"登录态失效"而跳登录页）。

**前端现状（`frontend-shell` 已交付）**：

- `lib/api/client.ts` 已具备「401 → 刷新 → 重放一次 → 失败跳转登录」，且已处理「令牌已被其他请求刷新则直接重放」与「刷新失败通知幂等」
- `lib/api/session.ts` 提供 `setTokenRefresher` / `setAuthFailureHandler` / `setAccessToken` / `resetSession` —— 刷新实现是未接线的占位
- `AppLayout` 在**受保护组内**注册 `setAuthFailureHandler`，并在卸载时置空（本 change 要把注册点上移到应用级）
- `/login` 是 `PlaceholderPage` 占位路由；路由表平铺，无公开/受保护之分
- `apiFetch` 目前不支持 `credentials` 选项（默认同源），跨源携带 Cookie 需要补
- **入口是 `main.tsx`**（`createBrowserRouter(routes)`），`app/AppRoutes.tsx` 只被测试使用——改路由结构时两处都要顾及

## Goals / Non-Goals

**Goals:**

- 让「会话」成为显式状态，而不是散落在请求副作用里
- 把既有刷新机制接线为真实行为，并用真实 HTTP 验证（而非只靠单测）
- 守卫行为可预测：未知态不渲染受保护内容、匿名态跳转且可回到原目标
- 登出路径在服务端失败时也能退出（不把用户困在界面里）

**Non-Goals:**

- 不引入状态管理之外的新依赖（沿用已有 Zustand + TanStack Query）
- 不做令牌持久化（`localStorage` / `sessionStorage` 一律不用）
- 不做权限驱动的 UI 显隐（`system_role` 仅用于展示与后续扩展）
- 不做账号管理界面（`users` 接口本期无前端消费方）

## Decisions

### F1. 会话引导用显式刷新，而非依赖 401 重放

**选择**：应用启动进入 `未知` 态 → 显式调用刷新接口 → 成功则再调 `GET /auth/me` 取账号并进入 `已登录`，失败进入 `匿名`。

**备选**：启动直接调 `GET /auth/me`，靠请求层的「401 → 刷新 → 重放」自动恢复。少写一个状态机，但未登录用户必然先吃一个 401 再跳转，且守卫在未知态下难以避免受保护内容闪现。

**理由**：spec 要求「恢复过程中不得渲染受保护内容」，显式状态机比复用副作用可控。刷新接口**不返回账号**（后端契约定为 `refresh` 只给令牌），所以引导是「refresh → me」两步。

### F2. 访问令牌仅存内存

**选择**：访问令牌保存在模块级变量（由 `session.ts` 持有），不写 `localStorage` / `sessionStorage`；整页刷新后靠刷新 Cookie 重新换取。

**理由**：XSS 读不到内存变量，显著降低长期凭据被窃取的面。代价是整页刷新多一次刷新往返。

### F3. 守卫实现为包裹组件

**选择**：`RequireAuth` 包裹受保护路由——未知态渲染全屏加载、匿名态 `Navigate` 到 `/login` 并把当前地址放进 `state.from`，登录成功后跳回。

**备选**：在 `AppLayout` 内用 `useEffect` 检测并跳转——渲染与跳转分离，易出现「先看到内容再被弹走」。

### F4. 跨源凭据通过 `apiFetch` 的 `credentials` 选项显式声明

**选择**：给 `RequestOptions` 增加 `credentials?: RequestCredentials` 并透传给 `fetch`；只有 `login` / `refresh` / `logout` 三个依赖 Cookie 的接口传 `credentials: "include"`，业务接口保持默认。

**理由**：登录与刷新必须让浏览器接受/发送跨源 Cookie；业务请求靠 Bearer，无需携带 Cookie（少一类凭证暴露面）。默认值不改，避免影响既有接口行为。后端已在 `auth-and-users` 中锁定 `Allow-Credentials: true` + 回显来源，此处是配套的前端一半。

### F5. 认证端点豁免 401 重放（避免自等待）

**选择**：`login` / `refresh` / `logout` 三个接口以「不注入令牌、不触发刷新重放」的方式发出（`auth: false` + `replayOn401: false`）。

**理由**：请求层对任何 401 都会尝试刷新，而刷新是**单例 Promise**。若刷新接口自身的 401 也走刷新重放，就会拿到"自己那个尚未 resolve 的 Promise"——请求自等待、永不返回。登出与登录同理（它们本就不该因为 401 去刷新）。

### F6. 刷新失败与登出的边界处理，以及处理器的注册位置

**选择**：
- **刷新失败**：由既有机制负责——`refreshAccessToken` 返回 `null` → 调用已幂等的 `notifyAuthFailure()` → 会话置为匿名并跳转登录页。
- **`setAuthFailureHandler` 的注册上移到应用级**（auth feature 初始化时注册一次），**移除 `AppLayout` 中的注册**：原先它挂在受保护组内，卸载即置空，而"跳登录"恰恰发生在离开受保护路由的过程中——依赖一个可能刚被卸载的组件是脆弱的。
- **登出**：无论服务端登出接口成功与否，**本地会话必须先清空**（内存令牌、账号、路由跳转）；服务端失败只记录告警（503 视为"服务端暂时不可用"，不作为登出失败处理）。
- **引导的两类失败要区分**：刷新令牌无效（401）→ 匿名态；网络/服务端故障（非 401）→ 引导失败态，给重试入口，不静默当作未登录。

**理由**：登出是用户表达"我要离开"的意图，不能因为后端或网络问题把人困在界面里；而"服务挂了"与"我没登录"对用户是完全不同的信息。

### F7. 路由表按公开 / 受保护分组

**选择**：路由表显式分两组——**公开**：`/login`、`/`（系统状态页，排障入口，未登录也应可访问）；**受保护**：其余（包在 `RequireAuth` 下）。

**理由**：后续新增业务页面只需加在受保护组内，守卫自然继承，避免"新页面忘了加守卫"。系统状态页保持公开，与它在 `frontend-shell` 中的定位（后端依赖排障）一致，也避免为了看健康状态必须先登录。

### F8. 测试用「会话状态」断言，不模拟 Cookie 细节

**选择**：msw 提供 login / refresh / logout / me 四类 handler（含凭据错误、限流 429、刷新失效等分支）；断言围绕**会话状态与路由结果**（登录后进入应用、刷新失败后回到登录页、登出后不携带旧令牌），不试图在 jsdom 里模拟真实 Cookie 行为。

**理由**：jsdom + msw 不执行浏览器 Cookie 语义，强行模拟只能验证"我们自己的假实现"；Cookie 是否真的流通属于真机联调（任务 5.x）的范畴。这与 `frontend-shell` 既有测试策略一致（HTTP 全拦截、不依赖后端）。

## Risks / Trade-offs

- **首屏多一次刷新往返**（F2、F1 的两步引导）→ 会话恢复期间的加载态由守卫统一承担；若体验要求更高，可让后端在刷新响应里附带账号（需回改 `auth-and-users` 的契约），本期不做
- **`credentials: "include"` 与后端 CORS 强耦合**（F4）→ 后端一旦改回通配符来源，浏览器会直接阻断请求；已由 `auth-and-users` 的测试锁定
- **jsdom 下无法验证真实 Cookie**（F8）→ Cookie 行为必须在真机联调中确认（任务 5.1–5.4），不可仅凭单测声称通过
- **500 响应可能缺 CORS 头**（`notes/scaffold/residual-risks.md` 第 3 条）→ 后端故障时前端可能读不到响应体；`auth-and-users` 任务 7.7 会给出结论；**在此之前**，登录页与服务端故障提示 MUST 对"无响应体"的情形做通用兜底（不依赖 `error_code`）
- **停用账号后最长 15 分钟的访问令牌窗口** → 前端在 `me` 返回 401 时立即置为匿名（场景已覆盖），不依赖令牌自然过期

## Migration Plan

实现顺序（也是 tasks 的顺序）：

1. 前置门禁：确认 `auth-and-users` 已实现（否则 5.x 无法执行）
2. 会话状态 + 请求层 `credentials` 透传 + 认证端点豁免重放 + 真实刷新接线 + 启动引导
3. 登录页（四态 + 限流提示）
4. 守卫、原目标回跳、外壳账号区与登出、`authFailureHandler` 注册点上移
5. 测试基建扩展与门禁
6. 真机联调（登录 → 整页刷新仍在线 → 停用后立即失效 → 登出后不可刷新）

**回滚**：撤销 `setTokenRefresher` 接线与路由分组即可回到占位状态；本 change 不引入数据或后端改动，无数据迁移。

## Open Questions

（无。）
