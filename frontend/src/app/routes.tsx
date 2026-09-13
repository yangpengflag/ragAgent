import type { RouteObject } from "react-router-dom";

import { AppLayout } from "@/app/AppLayout";
import { PlaceholderPage } from "@/app/PlaceholderPage";
import { SystemStatusPage } from "@/features/system-status/SystemStatusPage";

/**
 * 路由表。
 *
 * 除系统状态页外均为占位页——本 change 只交付外壳，
 * 业务页面由 knowledge-base / documents / chat / search 等 change 替换。
 */
export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppLayout />,
    children: [
      { index: true, element: <SystemStatusPage /> },
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
  {
    path: "/login",
    element: (
      <PlaceholderPage
        title="登录"
        description="登录由后续的账号与权限变更实现；此处为刷新令牌失效后的跳转目标。"
      />
    ),
  },
];
