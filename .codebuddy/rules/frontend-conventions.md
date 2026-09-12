---
trigger: always_on
---
# 前端编码规约

前端采用 **React 18 + Vite + TypeScript + Tailwind CSS 4 + shadcn/ui + lucide-react**。纯 SPA，无 SSR、无 BFF。以下为 SHOULD 级约定。

## 目录结构

```
frontend/src/
├── main.tsx              ← 入口
├── app/                  ← 路由表 + 布局壳 + 路由守卫
├── features/             ← 按业务域组织（auth / knowledge-base / documents / chat / admin）
│   └── <domain>/
│       ├── components/   ← 该域专属组件
│       ├── hooks/        ← 该域 hooks
│       └── api.ts        ← 该域 API 函数
├── components/ui/        ← shadcn/ui 基础组件（不手动修改）
├── components/           ← 跨域共享组件
├── lib/                  ← api client / utils / constants
└── types/                ← 共享类型
```

## 组件原则

- 函数组件 + hooks，不用 class
- 组件默认放 `features/<domain>/components/`；被 3 个以上域复用才提到 `components/`
- shadcn/ui 组件从 `@/components/ui/xxx` 导入，**不修改其源码**
- 每个组件文件只导出一个主组件
- 展示型组件不直接调 API，由容器组件/hook 注入

## 状态管理

- **服务端状态**：TanStack Query（`useQuery` / `useMutation`）——列表、详情、任务状态轮询
- **本地 UI 状态**：Zustand——抽屉开关、选中项、上传队列
- 不用 Redux；不把服务端数据塞进 Zustand 长期持有
- 轮询任务状态用 `refetchInterval`，任务终态（READY/FAILED）后停止轮询

## API 封装层

- 统一走 `lib/api/client.ts`（fetch 封装）：注入 baseURL、Bearer token、401 自动刷新重放、错误归一化
- 错误结构对齐后端：`ApiError { request_id, error_code, message, details? }`
- 每个域的 `api.ts` 只导出函数，不导出 fetch 细节
- **SSE 流式**（问答）单独封装，不用 TanStack Query

## 路由与守卫

- `react-router-dom` v6
- 守卫在 `app/` 层做（未登录跳 `/login`），不在每个页面内重复判断
- 知识库级权限由后端返回，前端仅做 UI 显隐，**不做安全边界**

## 样式

- 详见 `styling-conventions.md`（Tailwind 4 + shadcn/ui + lucide-react）
- 不写内联 style；不引入其它 UI 库

## 测试

- Vitest + React Testing Library + jsdom
- 测试文件与源文件同目录：`Xxx.test.tsx`
- 覆盖四态：Loading / Content / Empty / Error
- API 层用 `msw` 拦截，不打真实后端

## 通用禁忌

- 不在组件里写 `any`；类型来自 `types/` 或由 API 层定义
- 不做 camelCase/snake_case 转换层，字段名与后端 JSON 保持一致（snake_case）
- 不在前端拼接后端路由，跳转 URL 由后端返回
