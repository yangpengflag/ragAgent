## Why

项目定稿的前端技术栈是 **React 18 + Vite + TypeScript + Tailwind CSS 4 + shadcn/ui**，但仓库中尚无任何前端工程（`frontend/` 目录不存在）。后端骨架 change（`project-scaffold`）交付后，`GET /api/v1/health` 可用，此时需要有一个能跑起来、能连通后端、且具备统一布局与 API 封装的前端外壳，作为知识库管理、文档上传、问答等所有界面的承载容器。

若等第一个业务界面（如知识库列表）再搭工程，会同时引入工程配置、布局、请求层三类变更，出问题时难以定位，且每个界面各自封装请求会重演后端"多套错误格式"的问题。

## What Changes

- 新建 `frontend/` 工程：Vite + React 18 + TypeScript，dev server 端口 5173
- 初始化样式栈：Tailwind CSS 4、shadcn/ui（base-nova / neutral）、lucide-react；通过 `@fontsource` 引入 Inter 与 Plus Jakarta Sans 并注入 CSS 变量
- 实现应用外壳：根布局（侧边栏 + 内容区，移动端抽屉）、路由骨架（react-router v6）、导航占位项
- 实现 API 客户端层：统一 baseURL（来自 `VITE_API_BASE_URL`）、自动注入 Bearer token、401 时刷新并重放一次、错误归一化为 `ApiError { request_id, error_code, message, details? }`
- 接线数据层：TanStack Query（服务端状态）+ Zustand（本地 UI 状态）
- 实现**系统状态页**：调用后端 `GET /api/v1/health`，展示 MySQL / Redis / Milvus 三组件状态，覆盖 Loading / Content / Error / Empty 四态
- 建立测试与质量门禁：Vitest + React Testing Library + jsdom；API 拦截用 msw；`npm run test` / `lint` / `typecheck` / `build`
- 新增 `frontend/README.md`

**不在本 change 范围内**：登录/注册页、知识库管理界面、文档上传界面、问答界面、权限相关 UI、路由守卫的真实鉴权逻辑（本 change 只留占位点）、SSE 流式封装、i18n。

## Capabilities

### New Capabilities

- `frontend-shell`：前端工程与应用外壳——工程与样式栈初始化、布局与路由骨架、统一 API 客户端、数据层接线、系统状态页、测试与质量门禁。

### Modified Capabilities

（无。仓库此前无 `specs/`，且本 change 不改动后端能力。）

## Impact

- **新增目录/文件**：`frontend/`（`src/{app,components,components/ui,features,lib,types}`、`package.json`、`vite.config.ts`、`tsconfig.json`、`README.md`）
- **依赖引入**：`react`、`react-dom`、`react-router-dom`、`@tanstack/react-query`、`zustand`、`tailwindcss`、`lucide-react`、`@fontsource/*`；开发依赖 `vite`、`typescript`、`vitest`、`@testing-library/react`、`jsdom`、`msw`、`eslint`、`prettier`
- **环境变量**：`VITE_API_BASE_URL`（默认 `http://localhost:8000`），样例写入 `frontend/.env.example`
- **对后端的依赖**：系统状态页依赖 `project-scaffold` 交付的 `GET /api/v1/health`；后端未启动时该页必须显示 Error 态与重试入口，不得白屏
- **部署形态**：纯静态产物（`npm run build` → `dist/`），由后端或独立静态服务器托管（本期不配置托管方式）
