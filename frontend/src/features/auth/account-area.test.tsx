import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { AppProviders } from "@/app/providers";
import { AppRoutes } from "@/app/AppRoutes";
import { getAccessToken, resetSession } from "@/lib/api/session";
import { bootstrapSession } from "@/features/auth/bootstrap";
import { useSessionStore } from "@/features/auth/session-store";
import {
  authenticatedSessionHandlers,
  logoutFailureHandler,
  logoutHandler,
} from "@tests/msw/handlers";
import { server } from "@tests/msw/server";

function authenticatedSession() {
  server.use(...authenticatedSessionHandlers);
}

/** 渲染并等待引导落定（包在 act 内，避免 React "not wrapped in act" 告警） */
async function renderApp(path: string) {
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
    // 与组件内的引导共享同一个 Promise（去重），在 act 内 await 以免告警
    await bootstrapSession();
  });
  return utils;
}

describe("外壳账号区与登出", () => {
  afterEach(() => {
    resetSession();
    useSessionStore.getState().reset();
  });

  it("已登录时外壳展示当前账号", async () => {
    authenticatedSession();
    await renderApp("/chat");

    expect(await screen.findByText("admin")).toBeInTheDocument();
  });

  it("登出后回到登录页且不再持有旧访问令牌", async () => {
    authenticatedSession();
    server.use(logoutHandler);
    const user = userEvent.setup();
    await renderApp("/chat");

    await waitFor(() => {
      expect(screen.getByText("admin")).toBeInTheDocument();
    });
    // userEvent 自身已包 act：不要把点击再套一层 act（会导致事件派发与 act 冲突）
    await user.click(screen.getByRole("button", { name: "登出" }));

    await waitFor(() => {
      expect(screen.getByText("登录 EKB")).toBeInTheDocument();
    });
    expect(getAccessToken()).toBeNull();
    expect(useSessionStore.getState().status).toBe("anonymous");
  });

  it("在公开页登出同样回到登录页（无守卫可依赖，必须显式跳转）", async () => {
    authenticatedSession();
    server.use(logoutHandler);
    const user = userEvent.setup();
    await renderApp("/");

    await screen.findByText("admin");
    await user.click(screen.getByRole("button", { name: "登出" }));

    expect(await screen.findByText("登录 EKB")).toBeInTheDocument();
  });

  it("服务端登出失败（500）本地仍完成登出", async () => {
    authenticatedSession();
    server.use(logoutFailureHandler(500, "撤销失败"));
    const user = userEvent.setup();
    await renderApp("/chat");

    await screen.findByText("admin");
    await user.click(screen.getByRole("button", { name: "登出" }));

    // 登出是"我要离开"的意图：后端不可用也必须退出去
    await waitFor(() => {
      expect(screen.getByText("登录 EKB")).toBeInTheDocument();
    });
    expect(useSessionStore.getState().status).toBe("anonymous");
  });
});
