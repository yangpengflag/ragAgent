import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppProviders } from "@/app/providers";
import { AppRoutes } from "@/app/AppRoutes";
import { API_BASE_URL } from "@/lib/api/client";
import { server } from "@tests/msw/server";

/** 受保护路由需要已登录会话：给引导一个可用会话 */
function authenticatedSession() {
  server.use(
    http.post(`${API_BASE_URL}/api/v1/auth/refresh`, () =>
      HttpResponse.json({
        request_id: "req-r",
        access_token: "access-1",
        token_type: "Bearer",
        expires_in: 900,
      }),
    ),
    http.get(`${API_BASE_URL}/api/v1/auth/me`, () =>
      HttpResponse.json({
        request_id: "req-m",
        user: {
          id: "01936b2a-0000-7000-8000-000000000001",
          username: "admin",
          display_name: "系统管理员",
          system_role: "ADMIN",
        },
      }),
    ),
  );
}

/** 渲染并等待会话引导落定（包在 act 内，避免 React "not wrapped in act" 告警） */
async function renderApp(path = "/") {
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(
      <AppProviders>
        <MemoryRouter
          initialEntries={[path]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <AppRoutes />
        </MemoryRouter>
      </AppProviders>,
    );
  });
  return utils;
}

describe("应用外壳", () => {
  it("桌面宽度下呈现侧边栏与内容区两栏", async () => {
    await renderApp("/");

    const sidebar = screen.getByTestId("sidebar");
    // 通过断点类保证桌面显示、小屏隐藏（jsdom 不计算 CSS，断言类名而非布局）
    expect(sidebar.className).toContain("md:flex");
    expect(sidebar.className).toContain("hidden");
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("小屏下导航收起，点击入口后导航可见", async () => {
    const user = userEvent.setup();
    await renderApp("/");

    expect(screen.queryByTestId("sidebar-drawer")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "打开导航" }));

    const drawer = await screen.findByTestId("sidebar-drawer");
    expect(
      within(drawer).getByRole("link", { name: /知识库/ }),
    ).toBeInTheDocument();
  });

  it("当前路由对应的导航项带当前项标记", async () => {
    authenticatedSession();
    await renderApp("/knowledge-bases");

    await waitFor(() => {
      const activeLinks = screen
        .getAllByRole("link", { name: /知识库/ })
        .filter((link) => link.getAttribute("aria-current") === "page");
      expect(activeLinks).toHaveLength(1);
    });
  });

  it("侧边栏导航项不包含业务实现细节，仅占位路由", async () => {
    await renderApp("/");

    const sidebar = screen.getByTestId("sidebar");
    expect(within(sidebar).getByRole("link", { name: /系统状态/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      within(sidebar).getByRole("link", { name: /检索调试/ }),
    ).toBeInTheDocument();
  });
});
