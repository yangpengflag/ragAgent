import type { RouteObject } from "react-router-dom";

import { AppLayout } from "@/app/AppLayout";
import { PlaceholderPage } from "@/app/PlaceholderPage";
import { AuthFailureBridge } from "@/features/auth/AuthFailureBridge";
import { LoginPage } from "@/features/auth/LoginPage";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { SessionBootstrap } from "@/features/auth/SessionBootstrap";
import { SystemStatusPage } from "@/features/system-status/SystemStatusPage";

/**
 * 路由表（design F7：按「公开 / 受保护」显式分组）。
 *
 * 最外两层是无路径布局路由，随应用存活、不随页面卸载：
 * - `AuthFailureBridge`：刷新失败 → 跳登录的应用级接线
 * - `SessionBootstrap`：启动时恢复会话（refresh → me）
 *
 * 公开：`/`（系统状态，排障入口）、`/login`
 * 受保护：其余——**新增业务页面只要放进下面这组就自动继承守卫**，
 * 不需要记得"加守卫"。
 */
export const routes: RouteObject[] = [
  {
    element: <AuthFailureBridge />,
    children: [
      {
        element: <SessionBootstrap />,
        children: [
          { path: "/login", element: <LoginPage /> },
          {
            // 外壳（侧边栏）对公开页与受保护页共用：系统状态页免登录但保留导航，
            // 业务页面再套一层 RequireAuth
            element: <AppLayout />,
            children: [
              { index: true, element: <SystemStatusPage /> },
              {
                element: <RequireAuth />,
                children: [
                  {
                    path: "knowledge-bases",
                    element: (
                      <PlaceholderPage
                        title="知识库"
                        description="按业务域管理知识库、成员与权限。"
                      />
                    ),
                  },
                  {
                    path: "documents",
                    element: (
                      <PlaceholderPage
                        title="文档"
                        description="上传文档、查看解析与索引进度。"
                      />
                    ),
                  },
                  {
                    path: "chat",
                    element: (
                      <PlaceholderPage
                        title="问答"
                        description="基于知识库的检索增强问答。"
                      />
                    ),
                  },
                  {
                    path: "search",
                    element: (
                      <PlaceholderPage
                        title="检索调试"
                        description="直接查看召回片段与分数，用于调优检索。"
                      />
                    ),
                  },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
];
