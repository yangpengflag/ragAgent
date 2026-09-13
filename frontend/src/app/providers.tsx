import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useState } from "react";

import { wireTokenRefresher } from "@/features/auth/wire";

/**
 * 应用级 Provider 组合。
 * 服务端状态由 TanStack Query 承载；QueryClient 每次挂载新建，避免测试间串状态。
 */
export function AppProviders({ children }: { children: ReactNode }) {
  // 在渲染期而非 useEffect 中接线：子组件的 effect 早于父组件执行，
  // 放到 effect 里会出现"首屏请求发出时刷新实现尚未注入"的窗口。
  // 注入是幂等的（只是给模块级变量赋值），重复执行无副作用。
  wireTokenRefresher();

  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
