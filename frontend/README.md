# EKB 前端

企业知识库系统的前端工程：React 18 + Vite + TypeScript + Tailwind CSS 4 + shadcn/ui。

本工程当前处于**应用外壳**阶段：布局、路由、统一请求层、数据层与系统状态页已就绪；
知识库、文档上传、问答等业务页面由后续变更逐个交付。

## 环境要求

- Node.js ≥ 20（开发机为 22.x）
- npm ≥ 10

依赖与构建产物均落在本目录内，不写入 C 盘（本机 C 盘空间紧张）。

## 常用命令

```bash
npm install        # 安装依赖
npm run dev        # 开发服务器，http://localhost:5173
npm run build      # 类型检查 + 生产构建（产物 dist/）
npm run preview    # 预览构建产物
npm run test       # 运行测试（Vitest，单次）
npm run test:watch # 测试监听模式
npm run lint       # ESLint
npm run typecheck  # 仅类型检查
npm run format     # Prettier 格式化
```

## 配置

复制 `.env.example` 为 `.env` 并按需修改：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8000` | 后端 API 基址（不带尾部斜杠） |

## 目录结构

```
src/
├── main.tsx                 # 入口：字体、样式、Provider、Router
├── app/                     # 应用外壳：布局、路由表、Provider、占位页
├── components/
│   ├── ui/                  # shadcn/ui 基础组件（不手工修改）
│   └── PageContainer.tsx    # 跨域共享：页面统一容器
├── features/
│   ├── auth/                # 会话：登录页、守卫、引导、刷新与登出接线
│   └── system-status/       # 系统状态页（按业务域组织）
│       ├── api.ts           # 该域 API 函数（只声明路径与参数）
│       ├── hooks/           # 该域 hooks（TanStack Query）
│       └── components/      # 该域的展示组件
├── lib/
│   ├── api/                 # 统一请求层：client / errors / session
│   └── utils.ts             # cn() 等工具
├── store/                   # Zustand：本地 UI 状态
└── types/                   # 共享类型（字段名与后端 JSON 一致）
```

测试文件与被测源码**同目录**（`Xxx.test.tsx`）；共享测试基建在 `tests/`（msw handlers / server / setup）。

## 状态管理约定

- **服务端状态**走 TanStack Query（`useQuery` / `useMutation`），不放进 Zustand 长期持有
- **本地 UI 状态**走 Zustand（如导航抽屉开关）
- 不使用 Redux

## 请求层约定

- 所有请求经 `lib/api/client.ts` 的 `apiFetch`：拼基址、注入 `Authorization: Bearer`、401 后**刷新并重放一次**、错误归一化为 `ApiError`
- 错误字段与后端一致：`{ request_id, error_code, message, details? }`，**不做大小写转换**
- 刷新动作以单例 Promise 收敛：并发 401 只刷新一次
- 登录 / 刷新 / 登出三个端点以 `credentials: "include"` 发出（跨源 Cookie），且**豁免 401 重放**——否则刷新接口自身的 401 会等待"自己那个尚未 resolve 的 Promise"而永不返回

## 会话与守卫约定

- **访问令牌只存内存**（`lib/api/session.ts` 的模块级变量）：不写 `localStorage` / `sessionStorage`，整页刷新靠 `HttpOnly` 刷新 Cookie 重新换取
- 会话状态机在 `features/auth/session-store.ts`：`unknown`（恢复中，不渲染受保护内容）→ `authenticated` / `anonymous`；`bootstrap_error` 单独一支（后端抖动 ≠ 未登录，可重试）
- 启动引导 `refresh → me` 两步（刷新接口不返回账号），且**并发去重**——StrictMode 下 effect 会执行两次，而刷新令牌是轮换制，两次并发会互相作废
- 刷新失败分两类：`invalid`（401，登录态真的没了 → 置匿名并跳登录页）与 `transient`（503 / 网络错误，只是暂时拿不到令牌 → **不登出**，按普通错误提示）
- 路由分两组：**公开** `/`（系统状态排障入口）与 `/login`；**受保护** 其余，统一包在 `RequireAuth` 下——新增业务页面放进受保护组即自动继承守卫
- 登出：本地会话先清，服务端撤销失败只告警；**显式跳登录页**（公开页没有守卫会重新求值，不能依赖守卫重定向）
- "刷新失败 → 跳登录"的处理器注册在路由最外层的 `AuthFailureBridge`（无路径布局路由，随应用存活），不挂在会被卸载的布局组件上

## 测试

- Vitest + React Testing Library + jsdom
- 所有 HTTP 由 **msw** 拦截，测试**不依赖真实后端**：后端未启动时 `npm run test` 同样全绿
- `tests/msw/handlers.ts` 提供两类 fixtures：健康检查的四种形态（全部可用 / 部分不可用 / 请求失败 / 无组件数据），以及认证相关形态（登录成功 / 凭据错误 / 限流、刷新成功 / 失效 / 不可用、登出与登出失败、当前账号）

## 样式

遵循 `<harness>/rules/styling-conventions.md`（`<harness>/` 按 IDE 替换，见根 `AGENTS.md`）：

- Tailwind CSS 4（`src/styles.css` 中的 `@theme` 定义 Design Token），不写内联样式
- shadcn/ui 基础组件位于 `src/components/ui/`，**不定制样式、不加业务逻辑**；样式差异通过 `className` 覆盖
- ⚠️ **新增 shadcn 组件时必须补 `forwardRef` + `displayName`**：本项目为 React 18，而现行 shadcn 源码按 React 19 的「`ref` 作为普通 prop」语义生成，不补会丢失 Radix 经 Portal / Slot 注入的 ref（`<TooltipTrigger asChild><Button/></TooltipTrigger>` 这类组合会静默失效）
- 图标统一来自 `lucide-react`
- 字体：Inter（正文）与 Plus Jakarta Sans（标题），经 `@fontsource` 在 `main.tsx` 引入
- 禁止引入其它 UI 组件库与 CSS-in-JS（由 `tests/dependencies.test.ts` 守住）
