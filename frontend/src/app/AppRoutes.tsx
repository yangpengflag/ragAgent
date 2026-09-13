import { useRoutes } from "react-router-dom";

import { routes } from "@/app/routes";

/** 路由渲染入口：把路由表交给 react-router 渲染 */
export function AppRoutes() {
  return useRoutes(routes);
}
