import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { AppProviders } from "@/app/providers";
import { AppRoutes } from "@/app/AppRoutes";
import { API_BASE_URL } from "@/lib/api/client";
import { resetSession } from "@/lib/api/session";
import { useSessionStore } from "@/features/auth/session-store";
import { server } from "@tests/msw/server";

const REFRESH_URL = `${API_BASE_URL}/api/v1/auth/refresh`;
const LOGIN_URL = `${API_BASE_URL}/api/v1/auth/login`;
const ME_URL = `${API_BASE_URL}/api/v1/auth/me`;

/** 无有效刷新令牌：引导以 401 结束 → 匿名 */
function anonymousSession() {
  server.use(
    http.post(REFRESH_URL, () =>
      HttpResponse.json(
        {
          request_id: "req-401",
          error_code: "unauthorized",
          message: "刷新令牌无效",
        },
        { status: 401 },
      ),
    ),
  );
}

/**
 * 渲染并等待引导落定。
 *
 * 必须包在 `act` 里：引导是异步的（refresh → me），其状态更新若发生在 act 之外，
 * React 会打出 "not wrapped in act(...)" 告警（任务 4.3 要求测试输出无告警）。
 */
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
  });
  return utils;
}

describe("路由守卫", () => {
  afterEach(() => {
    resetSession();
    useSessionStore.getState().reset();
  });

  it("未登录访问受保护路由：跳转登录页，且不渲染该路由内容", async () => {
    anonymousSession();
    await renderApp("/chat");

    expect(await screen.findByText("登录 EKB")).toBeInTheDocument();
    expect(screen.queryByText("功能建设中")).not.toBeInTheDocument();
  });

  it("未登录可访问登录页", async () => {
    anonymousSession();
    await renderApp("/login");

    expect(await screen.findByText("登录 EKB")).toBeInTheDocument();
  });

  it("未登录可访问系统状态页（排障入口）", async () => {
    anonymousSession();
    await renderApp("/");

    // 侧边栏也有"系统状态"导航项，故按页面标题断言
    expect(
      await screen.findByRole("heading", { name: "系统状态", level: 1 }),
    ).toBeInTheDocument();
  });

  it("引导期间不渲染受保护内容（未知态呈现加载态）", async () => {
    // 闸门在发请求前就建好：断言未知态时请求必然还挂着
    let openGate!: (response: Response) => void;
    const gate = new Promise<Response>((resolve) => {
      openGate = resolve;
    });
    server.use(http.post(REFRESH_URL, () => gate));
    await renderApp("/chat");

    // 引导未完成时：既没有受保护内容，也不该已经跳到登录页
    expect(screen.queryByText("功能建设中")).not.toBeInTheDocument();
    expect(screen.queryByText("登录 EKB")).not.toBeInTheDocument();
    expect(useSessionStore.getState().status).toBe("unknown");

    openGate(
      HttpResponse.json(
        {
          request_id: "req-401",
          error_code: "unauthorized",
          message: "刷新令牌无效",
        },
        { status: 401 },
      ),
    );
    await waitFor(() => {
      expect(screen.getByText("登录 EKB")).toBeInTheDocument();
    });
  });

  it("未登录访问受保护路由后完成登录：自动回到原目标", async () => {
    anonymousSession();
    server.use(
      http.post(LOGIN_URL, () =>
        HttpResponse.json({
          request_id: "req-login",
          access_token: "access-1",
          token_type: "Bearer",
          expires_in: 900,
          user: {
            id: "01936b2a-0000-7000-8000-000000000001",
            username: "admin",
            display_name: "系统管理员",
            system_role: "ADMIN",
          },
        }),
      ),
    );
    const user = userEvent.setup();
    await renderApp("/chat");

    expect(await screen.findByText("登录 EKB")).toBeInTheDocument();
    await user.type(screen.getByLabelText("用户名"), "admin");
    await user.type(screen.getByLabelText("密码"), "secret");
    await user.click(screen.getByRole("button", { name: "登录" }));

    // 回到原目标 /chat（侧边栏也有"问答"导航项，故按标题角色断言）
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: "问答", level: 1 }),
      ).toBeInTheDocument();
    });
  });

  it("已登录访问受保护路由：正常渲染", async () => {
    server.use(
      http.post(REFRESH_URL, () =>
        HttpResponse.json({
          request_id: "req-r",
          access_token: "access-1",
          token_type: "Bearer",
          expires_in: 900,
        }),
      ),
      http.get(ME_URL, () =>
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
    await renderApp("/chat");

    expect(await screen.findByText("功能建设中")).toBeInTheDocument();
  });
});
