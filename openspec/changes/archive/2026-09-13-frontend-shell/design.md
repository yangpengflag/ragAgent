## Context

仓库当前无任何前端工程。后端骨架 change（`project-scaffold`）将交付 `GET /api/v1/health`，其响应契约为 `{ request_id, status: "ok"|"degraded", components: { mysql|redis|milvus: { status, error } } }`，且任一依赖不可用时仍返回 200。

本机环境：Node 与 npm 可用；**C 盘仅剩约 2.6 GB**，因此 `node_modules/`、`dist/` 等必须落在工作区（D 盘），不得使用 C 盘上的全局缓存目录（若 npm 缓存默认在 `%LOCALAPPDATA%\npm-cache`，需评估占用或改到 D 盘）。

动机见 `proposal.md`，需求见 `specs/frontend-shell/spec.md`。本文件只写"怎么做"。

## Goals / Non-Goals

**Goals:**

- 建立可运行、可构建、可测试的前端工程与应用外壳
- 建立统一的 API 客户端（基址、鉴权、401 刷新重放、错误归一化），避免每个界面各自封装
- 用"系统状态页"验证前后端真实联通，并作为四态（Loading/Content/Empty/Error）的样板实现
- 保证依赖与构建产物不污染 C 盘

**Non-Goals:**

- 不实现任何业务界面（登录、知识库、文档上传、问答）
- 不实现真实鉴权逻辑（只留刷新重放机制与登录跳转占位）
- 不封装 SSE 流式（问答 change 再做）
- 不做 i18n、暗色模式落地、性能调优
- 不配置静态资源托管方式

## Decisions

### F1. Vite 构建 React SPA，不用 Next.js

**选择**：Vite + React 18 + TypeScript 纯 SPA，dev server 5173，产物 `dist/`。

**备选**：Next.js —— 引入 SSR/RSC 与 BFF 概念，与"前后端分离"定位冲突；且后续 SSE 流式在 RSC 下反而更绕。

**理由**：企业内部门禁系统无需 SEO/SSR；Vite 冷启动与构建开销显著更低，在本机资源受限的情况下更合适。

### F2. 样式栈：Tailwind 4 + shadcn/ui + lucide-react，字体走 @fontsource

**选择**：按 `styling-conventions.md` 锁定栈；Inter 与 Plus Jakarta Sans 通过 `@fontsource` 包在入口引入（Vite 项目不使用 `next/font`）；shadcn/ui 生成于 `src/components/ui/`，不手工修改。

**备选**：引入其它 UI 库（Element Plus / AntD 等）—— 与样式规约冲突；CDN 引入字体 —— 离线与内网环境不可用。

**理由**：复用工作区既有样式规约与项目级 Design Token，零额外设计成本。

### F3. 目录按业务域组织，状态分层

**选择**：`src/features/<domain>/{components,hooks,api.ts}`；服务端状态用 TanStack Query，本地 UI 状态用 Zustand；共享组件与 shadcn 基础组件分别在 `src/components/` 与 `src/components/ui/`。

**备选**：按技术层平铺（components/pages/store 分离）—— 业务域内聚差，文件跳转成本高。

**理由**：`frontend-conventions.md` 已定此结构；业务域内聚便于后续按 change 增量交付。

### F4. API 客户端：fetch 封装 + 单例刷新 Promise + 错误归一化

**选择**：`lib/api/client.ts` 基于 `fetch` 封装，职责限于基址、令牌注入、401 刷新重放、错误归一化。刷新动作以**单例 Promise** 保证并发请求只刷新一次（避免多个 401 同时触发多次刷新）。

**备选**：① axios 拦截器 —— 多一个依赖，且刷新重放的并发控制仍需自己写；② 每个 `features/*/api.ts` 各自处理 —— 重演"多套错误格式"。

**理由**：刷新重放的并发控制是唯一有实质复杂度的部分，集中在客户端层实现；业务 API 函数只关心路径与参数。

### F5. 字段名不做转换层

**选择**：TypeScript 类型字段名与后端 JSON 完全一致（snake_case，如 `error_code`、`request_id`）。

**备选**：加 camelCase 转换层 —— 多一层映射与出错面，且与 `api-conventions.md` 冲突。

**理由**：契约一致性优先；规约已明确禁止转换层。

### F6. 测试：Vitest + RTL + msw，不打真实后端

**选择**：组件测试覆盖四态与交互；所有 HTTP 由 msw 拦截，提供"全部可用 / 部分不可用 / 请求失败"三种 handler 便于断言系统状态页的四态。

**备选**：连真实后端跑测试 —— 测试不稳定且依赖中间件启停。

**理由**：满足"测试不依赖真实后端"的需求，也让四态可确定性地被覆盖。

### F7. 环境变量与端口

**选择**：`VITE_API_BASE_URL` 默认 `http://localhost:8000`，样例写入 `frontend/.env.example`；dev server 端口固定 5173（与 `project.md` 端口约定一致）。

**备选**：端口写在代码里 —— 违反配置外置原则。

### F8. 依赖与产物落 D 盘

**选择**：工程位于 `frontend/`（工作区在 D 盘），`node_modules/`、`dist/` 与构建缓存均在项目内；`frontend/.gitignore` 排除 `node_modules/`、`dist/`、`.env*.local`。若 npm 全局缓存位于 C 盘且占用显著，改用 `npm config set cache D:\npm-cache`。

**备选**：依赖装到 C 盘全局目录 —— C 盘仅剩约 2.6 GB，风险高。

## Risks / Trade-offs

- **C 盘空间紧张** → 依赖与产物全部留在 `frontend/` 内；工程初始化时确认 npm 缓存位置，必要时迁移；构建前记录 C 盘剩余。
- **shadcn/ui 初始化是交互式命令** → 明确记录初始化步骤与所选主题（base-nova / neutral），避免不同机器生成结果不一致；初始化结果入仓。
- **后端未启动时系统状态页的体验** → 这是必须覆盖的 Error 态而非异常场景；msw handler 覆盖 500 与网络错误两种失败形态。
- **401 刷新重放的并发边界** → 用单例 Promise 收敛；若刷新中又出现新 401，复用同一 Promise 而非再发一次刷新。
- **Vite 与 Tailwind 4 的版本兼容** → 锁定版本并写入 `package.json`，避免 `@latest` 带来的隐性升级。
- **路由守卫占位与真实鉴权的衔接** → 本 change 只留跳转占位，真实鉴权在 auth change 接入；避免此处提前实现未定的登录态存储方式。
- **React 18 与 shadcn/ui 现行源码的写法差异（实施期发现）** → 现行 shadcn/ui 源码按 React 19 的"`ref` 作为普通 prop"写法生成，在 **React 18** 下会丢失 Radix 经 Portal/Slot 注入的 ref：实测 `SheetOverlay` 在打开抽屉时报 `Warning: Function components cannot be given refs`，焦点管理随之失效。因此 `src/components/ui/` 下的基础组件以 **React 18 规范形态**（`React.forwardRef` + `displayName`）落库，其余样式与结构保持 shadcn 原样；后续用 `shadcn add` 新增组件时需同样补 `forwardRef`。该处理不改变 R6「基础组件不被手工定制」的意图（不 fork 样式、不加业务逻辑）。

## Migration Plan

1. 创建 `frontend/` 工程（Vite + React + TS），锁定依赖版本
2. 初始化 Tailwind 4、shadcn/ui、lucide 与 @fontsource 字体
3. 实现应用外壳（布局、侧边栏、路由、导航占位）
4. 实现 API 客户端（基址、令牌注入、401 刷新重放、错误归一化）
5. 接线 TanStack Query 与 Zustand
6. 实现系统状态页（四态完整覆盖）
7. 建立测试基建（Vitest + RTL + msw）与质量门禁
8. 真机验证：启动前端与后端，系统状态页显示三组件可用；停掉 Redis 后页面显示该组件不可用；停掉后端后显示 Error 态且重试可用

**回滚**：本 change 为全新工程，无存量；如需撤销，删除 `frontend/` 目录即可，不影响后端与数据库。

## Open Questions

（无。所有决策均可在后续 change 增量演进，不影响本 change 的规格、方案与任务拆分。）
