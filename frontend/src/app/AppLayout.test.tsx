import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppProviders } from "@/app/providers";
import { AppRoutes } from "@/app/AppRoutes";

function renderApp(path = "/") {
  return render(
    <AppProviders>
      <MemoryRouter
        initialEntries={[path]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AppRoutes />
      </MemoryRouter>
    </AppProviders>,
  );
}

describe("应用外壳", () => {
  it("桌面宽度下呈现侧边栏与内容区两栏", () => {
    renderApp("/");

    const sidebar = screen.getByTestId("sidebar");
    // 通过断点类保证桌面显示、小屏隐藏（jsdom 不计算 CSS，断言类名而非布局）
    expect(sidebar.className).toContain("md:flex");
    expect(sidebar.className).toContain("hidden");
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("小屏下导航收起，点击入口后导航可见", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    renderApp("/");

    expect(screen.queryByTestId("sidebar-drawer")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "打开导航" }));

    const drawer = await screen.findByTestId("sidebar-drawer");
    expect(
      within(drawer).getByRole("link", { name: /知识库/ }),
    ).toBeInTheDocument();
  });

  it("当前路由对应的导航项带当前项标记", () => {
    renderApp("/knowledge-bases");

    const activeLinks = screen
      .getAllByRole("link", { name: /知识库/ })
      .filter((link) => link.getAttribute("aria-current") === "page");

    expect(activeLinks).toHaveLength(1);
  });

  it("侧边栏导航项不包含业务实现细节，仅占位路由", () => {
    renderApp("/");

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
