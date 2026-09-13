import { useEffect } from "react";
import { Outlet, useNavigate } from "react-router-dom";

import { setAuthFailureHandler } from "@/lib/api/session";

import { createAuthFailureHandler } from "./auth-failure";

/**
 * 应用级「刷新失败」接线点。
 *
 * 原先注册在 `AppLayout` 内：而"跳登录"恰恰发生在离开受保护路由的过程中，
 * 依赖一个可能刚被卸载的组件是脆弱的（design F6）。这里作为**无路径布局路由**
 * 挂在路由表最外层，随应用存活，不随任何页面卸载。
 */
export function AuthFailureBridge() {
  const navigate = useNavigate();

  useEffect(() => {
    setAuthFailureHandler(createAuthFailureHandler(navigate));
    return () => setAuthFailureHandler(null);
  }, [navigate]);

  return <Outlet />;
}
