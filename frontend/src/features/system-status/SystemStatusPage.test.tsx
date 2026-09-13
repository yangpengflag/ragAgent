import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, delay, http } from "msw";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppProviders } from "@/app/providers";
import { AppRoutes } from "@/app/AppRoutes";

import {
  HEALTH_URL,
  healthDegradedHandler,
  healthEmptyHandler,
  healthOkHandler,
} from "@tests/msw/handlers";
import { server } from "@tests/msw/server";

function renderPage() {
  return render(
    <AppProviders>
      <MemoryRouter
        initialEntries={["/"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AppRoutes />
      </MemoryRouter>
    </AppProviders>,
  );
}

describe("系统状态页", () => {
  it("请求未完成时展示加载占位", async () => {
    server.use(
      http.get(HEALTH_URL, async () => {
        await delay(50);
        return HttpResponse.json({
          request_id: "req-slow",
          status: "ok",
          components: { mysql: { status: "ok", error: null } },
        });
      }),
    );

    renderPage();

    expect(screen.getByTestId("system-status-loading")).toBeInTheDocument();
    expect(screen.queryByTestId("system-status-content")).not.toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("system-status-content")).toBeInTheDocument();
    });
  });

  it("三组件均可用时展示整体 ok 与三个组件可用", async () => {
    server.use(healthOkHandler);
    renderPage();

    const content = await screen.findByTestId("system-status-content");

    expect(within(content).getByTestId("overall-status")).toHaveTextContent(
      "ok",
    );
    expect(within(content).getByText("MySQL")).toBeInTheDocument();
    expect(within(content).getByText("Redis")).toBeInTheDocument();
    expect(within(content).getByText("Milvus")).toBeInTheDocument();
    expect(within(content).getAllByText("可用")).toHaveLength(3);
  });

  it("存在不可用组件时展示降级并标出该组件与原因", async () => {
    server.use(healthDegradedHandler);
    renderPage();

    const content = await screen.findByTestId("system-status-content");

    expect(within(content).getByTestId("overall-status")).toHaveTextContent(
      "degraded",
    );
    expect(within(content).getAllByText("不可用")).toHaveLength(1);
    expect(
      within(content).getByText(/Error 111 connecting to localhost:6379/),
    ).toBeInTheDocument();
  });

  it("请求失败（500）时展示错误描述与重试按钮，点击后重新发起请求", async () => {
    let requestCount = 0;
    server.use(
      http.get(HEALTH_URL, () => {
        requestCount += 1;
        return HttpResponse.json(
          {
            request_id: "req-500",
            error_code: "internal_error",
            message: "数据库连接失败",
          },
          { status: 500 },
        );
      }),
    );

    const user = userEvent.setup();
    renderPage();

    const errorCard = await screen.findByTestId("system-status-error");
    expect(within(errorCard).getByTestId("error-message")).toHaveTextContent(
      "数据库连接失败",
    );
    expect(requestCount).toBe(1);

    await user.click(within(errorCard).getByRole("button", { name: /重试/ }));

    await waitFor(() => {
      expect(requestCount).toBe(2);
    });
  });

  it("请求失败（网络错误）时展示连接失败提示", async () => {
    server.use(http.get(HEALTH_URL, () => HttpResponse.error()));

    renderPage();

    const errorCard = await screen.findByTestId("system-status-error");
    expect(within(errorCard).getByTestId("error-message")).toHaveTextContent(
      /无法连接到服务器/,
    );
  });

  it("后端未返回组件数据时展示空态引导", async () => {
    server.use(healthEmptyHandler);

    renderPage();

    expect(await screen.findByTestId("system-status-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("system-status-content")).not.toBeInTheDocument();
  });
});
