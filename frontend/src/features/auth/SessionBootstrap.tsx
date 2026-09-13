import { useEffect } from "react";
import { Outlet } from "react-router-dom";

import { bootstrapSession } from "./bootstrap";

/**
 * 启动引导：挂载时显式刷新一次会话（design F1）。
 *
 * 与"等第一个请求 401 再被动刷新"的区别：未登录用户不会先吃一个 401，
 * 且守卫能在恢复完成前保持未知态，避免受保护内容闪现。
 * 放在无路径布局路由里：随应用启动执行一次，不随页面切换重复触发。
 */
export function SessionBootstrap() {
  useEffect(() => {
    void bootstrapSession();
  }, []);

  return <Outlet />;
}
