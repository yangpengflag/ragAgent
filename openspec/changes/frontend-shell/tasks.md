## 1. 工程与样式栈初始化

- [ ] 1.1 用 Vite 创建 `frontend/` 工程（React 18 + TypeScript），锁定依赖版本，确认 `node_modules/` 位于工作区（D 盘）
- [ ] 1.2 红灯：写测试——构建命令可成功产出 `dist/`；类型检查无错误
- [ ] 1.3 绿灯：配置 `vite.config.ts`（dev 端口 5173）与 `tsconfig.json`（路径别名 `@/`）
- [ ] 1.4 初始化 Tailwind CSS 4 与全局样式，验证工具类生效
- [ ] 1.5 初始化 shadcn/ui（base-nova / neutral）与 lucide-react，确认基础组件生成于 `src/components/ui/` 且未被手改
- [ ] 1.6 通过 `@fontsource` 引入 Inter 与 Plus Jakarta Sans，注入 `--font-sans` / `--font-heading` 变量
- [ ] 1.7 配置 lint（eslint + prettier）与 `npm run lint` / `typecheck` / `build` / `test` 脚本
- [ ] 1.8 编写 `frontend/.gitignore`（排除 `node_modules/`、`dist/`、`.env*.local`）与 `frontend/.env.example`（`VITE_API_BASE_URL`）
- [ ] 1.9 红灯：写测试——工程依赖中不包含样式规约禁止的 UI 库
- [ ] 1.10 确认 npm 缓存位置不在 C 盘（必要时 `npm config set cache D:\npm-cache`），并记录 C 盘剩余空间

## 2. 应用外壳：布局与路由

- [ ] 2.1 红灯：写测试——桌面宽度下渲染呈现侧边栏与内容区两栏
- [ ] 2.2 绿灯：实现根布局（侧边栏 `w-64` + 内容区，符合 `styling-conventions.md` 应用布局约定）
- [ ] 2.3 红灯：写测试——移动宽度下侧边栏收起，且存在可打开导航的入口，点击后导航可见
- [ ] 2.4 绿灯：实现响应式收起与抽屉
- [ ] 2.5 红灯：写测试——当前路由对应导航项呈现选中态并带当前项标记（`aria-current`）
- [ ] 2.6 绿灯：接入 react-router v6，配置路由表与占位导航项
- [ ] 2.7 重构：抽出导航配置数据，布局组件不内含业务路由细节

## 3. API 客户端层

- [ ] 3.1 红灯：写测试——已持有令牌时请求头包含 `Authorization: Bearer <token>`
- [ ] 3.2 绿灯：实现 `lib/api/client.ts` 基址与令牌注入（基址取自 `VITE_API_BASE_URL`，默认 8000）
- [ ] 3.3 红灯：写测试——服务端错误响应被归一化为 `ApiError`，含 `request_id` / `error_code` / `message` 且与后端字段名一致
- [ ] 3.4 绿灯：实现错误归一化
- [ ] 3.5 红灯：写测试——请求返回 401 且刷新有效时，自动刷新并重放一次，调用方得到成功结果
- [ ] 3.6 绿灯：实现 401 刷新重放（刷新动作以单例 Promise 收敛，避免并发重复刷新）
- [ ] 3.7 红灯：写测试——刷新失败时跳转登录页且不重复重放原请求
- [ ] 3.8 绿灯：实现刷新失败跳转（跳转目标为占位登录路由）
- [ ] 3.9 重构：业务 API 函数只声明路径与参数，不含鉴权与错误处理样板

## 4. 数据层接线

- [ ] 4.1 红灯：写测试——QueryClient Provider 可用，组件可拿到查询数据
- [ ] 4.2 绿灯：接入 TanStack Query
- [ ] 4.3 红灯：写测试——Zustand store 可读写并在组件间共享本地 UI 状态
- [ ] 4.4 绿灯：接入 Zustand（本 change 仅用于外壳状态，如导航抽屉开关）
- [ ] 4.5 重构：明确约定服务端状态走 Query、UI 状态走 Zustand，README 中写明

## 5. 系统状态页（四态样板）

- [ ] 5.1 红灯：写测试——请求未完成时展示加载占位
- [ ] 5.2 绿灯：实现加载态骨架（Skeleton）
- [ ] 5.3 红灯：写测试——三组件均可用时展示整体 `ok` 并列出三个组件为可用
- [ ] 5.4 绿灯：实现状态展示（整体状态 + 三组件列表）
- [ ] 5.5 红灯：写测试——存在不可用组件时整体显示降级，并标出该组件及其原因
- [ ] 5.6 绿灯：实现降级态与原因展示
- [ ] 5.7 红灯：写测试——请求失败（500 与网络错误两种）时展示错误描述与重试按钮，点击后重新发起请求
- [ ] 5.8 绿灯：实现错误态与重试
- [ ] 5.9 红灯：写测试——后端返回无 `components` 数据时展示空态引导
- [ ] 5.10 绿灯：实现空态
- [ ] 5.11 重构：抽出健康状态的类型定义与展示组件，页面只做编排

## 6. 测试基建与门禁

- [ ] 6.1 配置 Vitest + React Testing Library + jsdom
- [ ] 6.2 配置 msw，提供健康检查的三组 handler（全部可用 / 部分不可用 / 请求失败）
- [ ] 6.3 验证：`npm run test` 全绿且**后端未启动**时同样通过
- [ ] 6.4 验证：`npm run lint`、`typecheck`、`build` 均无错误
- [ ] 6.5 编写 `frontend/README.md`（启动、测试、构建命令与目录说明）

## 7. 真机联调与收尾

- [ ] 7.1 启动后端与前端，访问系统状态页，确认展示 MySQL / Redis / Milvus 三组件均为可用
- [ ] 7.2 停掉 Redis 容器后刷新页面，确认该组件显示为不可用并给出原因，其余仍可用
- [ ] 7.3 停掉后端后进入页面，确认显示 Error 态，点击重试可重新发起请求
- [ ] 7.4 复查：API 字段名与后端一致（snake_case）、图标全部来自 lucide-react、shadcn 组件未被手改
- [ ] 7.5 更新 `AGENTS.md` 的前端目录与命令说明，提交变更
