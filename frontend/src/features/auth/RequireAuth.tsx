import { AlertTriangle, Loader2 } from "lucide-react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

import { bootstrapSession } from "./bootstrap";
import { useSessionStore } from "./session-store";

/**
 * 受保护路由守卫。
 *
 * 三态语义（design F3/F6）：
 * - `unknown` → 全屏加载：恢复未完成时不渲染受保护内容，也不呈现"未登录"这种误导界面
 * - `anonymous` → 跳登录页并带上原目标，供登录后回跳
 * - `bootstrap_error` → **不是未登录**，给重试入口（后端抖动不该被当成"你没登录"）
 */
export function RequireAuth() {
  const status = useSessionStore((state) => state.status);
  const bootstrapError = useSessionStore((state) => state.bootstrapError);
  const location = useLocation();

  if (status === "unknown") {
    return (
      <div
        className="flex min-h-screen items-center justify-center"
        data-testid="session-loading"
      >
        <Loader2 className="size-6 animate-spin text-slate-400" aria-hidden="true" />
        <span className="sr-only">正在恢复登录会话</span>
      </div>
    );
  }

  if (status === "bootstrap_error") {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <Card className="w-full max-w-md">
          <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
            <AlertTriangle className="size-6 text-amber-600" aria-hidden="true" />
            <p className="text-base font-semibold text-slate-900">
              无法恢复登录状态
            </p>
            <p className="text-sm text-slate-500">{bootstrapError}</p>
            <Button type="button" onClick={() => void bootstrapSession()}>
              重试
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (status === "anonymous") {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: `${location.pathname}${location.search}` }}
      />
    );
  }

  return <Outlet />;
}
