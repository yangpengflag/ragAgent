# `frontend-shell` 残留风险与后续待办

> 本文件记录**已接受但不修**的事项，以及必须留给后续 change 的接口约定。
> 来源：第 6 轮独立评审（30 个用例全绿、lint / typecheck / build 无错之后仍成立）。

## 1. Empty 态是前向兼容分支，真实链路不可达

后端的 `GET /api/v1/health` 恒定返回 mysql / redis / milvus 三个组件，`components` 永不为空，
因此系统状态页的「空态」在真实联调中**不会出现**（单测用合成的空响应覆盖）。

保留原因：spec R4 明确要求覆盖「无数据」态；且后端契约一旦变化（按需返回组件、或响应体被网关裁剪）时不至于白屏。
若将来后端改为按需返回组件，此分支自动生效，无需改前端。

## 2. `127.0.0.1:5173` 访问路径未覆盖

- Vite dev server 未设 `server.host`，实测只绑定 `localhost`（IPv6 `::1`），`http://127.0.0.1:5173` 打不开
- 后端 CORS 白名单只放行 `http://localhost:5173`（`.env` 的 `APP_CORS_ORIGINS`）

文档化的访问路径（`http://localhost:5173`）自洽，故本 change 不修。
若需要支持 `127.0.0.1`：Vite 加 `server.host: true`，并把 `http://127.0.0.1:5173` 追加到后端 CORS 白名单。
**注意**：`server.host: true` 会把 dev server 暴露到局域网，内网环境需评估。

## 3. `network_error` 是客户端自造错误码

`api-conventions.md` 的错误码表里没有 `network_error`；前端在请求未到达服务端（`fetch` 抛错）时用它，
`status` 置 `0`。属客户端保留码，建议后续在 `api-conventions.md` 补一行说明，避免后端误以为要发这个码。

## 4. 错峰 401 的收敛方式与遗留窗口

实现：401 重放前先比对「当前令牌是否已与发起请求时不同」——不同则说明别的请求已刷新，**直接重放不再刷新**；
相同才走单例刷新。这样错峰 401 不会重复刷新，且不依赖时间窗。

遗留窗口：两个请求都用**同一个**过期令牌发出、且刷新失败时，两者都会走刷新路径（单例保证只刷新一次），
`notifyAuthFailure()` 已做幂等去重，因此跳转只发生一次。但如果未来刷新实现「返回同一个新令牌」，
理论上可能出现「重放后仍 401 → 不再重放」的快速失败，这是有意的（避免死循环）。

## 5. auth change 接入时的接口约定

已在 `AppLayout` 接线，后续只需替换实现：

- `setTokenRefresher(() => Promise<string | null>)` —— 刷新令牌，**失败必须返回 `null`/空值**（空串按失败处理）
- `setAuthFailureHandler(() => void)` —— 刷新失败后的跳转（当前为 `navigate("/login", {replace:true})`）
- `setAccessToken(token)` / `resetSession()` —— 登录成功 / 登出时调用

**待定**：登录态存储方式（access 存内存、refresh 走 httpOnly cookie 是当前设想，未实现）。

## 6. 新增 shadcn 组件必须补 `forwardRef`

现行 shadcn 源码按 React 19 的「`ref` 作为普通 prop」语义生成，在 React 18 下会丢 ref。
`src/components/ui/` 现有 6 个组件（button / badge / card / alert / skeleton / sheet）已全部适配，
但后续 `shadcn add` 生成的组件（Input、Select、Tooltip、DropdownMenu 等）**必须同样补 `forwardRef` + `displayName`**，
否则 `<TooltipTrigger asChild>` / `<DropdownMenuTrigger asChild>` 这类组合会静默失效。

已在 `frontend/README.md` 样式章节与 spec R6 的例外条款中记录。

## 7. `AppLayout.test.tsx` 的响应式断言属实现细节守卫

jsdom 不计算 CSS，`expect(sidebar.className).toContain("md:flex")` 实质是「防止有人删掉断点类」的守卫，
**不验证真实的响应式布局**。真实窄屏行为已在浏览器中手工验证（390px 下侧栏从 a11y 树消失、抽屉可开）。
若将来引入浏览器端组件测试（Playwright / Vitest browser mode），应替换为真实视口断言。
