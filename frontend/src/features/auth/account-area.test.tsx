import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { AppProviders } from "@/app/providers";
import { AppRoutes } from "@/app/AppRoutes";
import { API_BASE_URL } from "@/lib/api/client";
import { getAccessToken, resetSession } from "@/lib/api/session";
import { useSessionStore } from "@/features/auth/session-store";
import { server } from "@tests/msw/server";

const REFRESH_URL = `${API_BASE_URL}/api/v1/auth/refresh`;
const ME_URL = `${API_BASE_URL}/api/v1/auth/me`;
const LOGOUT_URL = `${API_BASE_URL}/api/v1/auth/logout`;

const ACCOUNT = {
  id: "01936b2a-0000-7000-8000-000000000001",
  username: "admin",
  display_name: "系统管理员",
  system_role: "ADMIN",
};

function authenticatedSession() {
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
      HttpResponse.json({ request_id: "req-m", user: ACCOUNT }),
    ),
  );
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
    server.use(
      http.post(LOGOUT_URL, () => new HttpResponse(null, { status: 204 })),
    );
    const user = userEvent.setup();
    await renderApp("/chat");

    await screen.findByText("admin");
    await user.click(screen.getByRole("button", { name: "登出" }));

    expect(await screen.findByText("登录 EKB")).toBeInTheDocument();
    expect(getAccessToken()).toBeNull();
    expect(useSessionStore.getState().status).toBe("anonymous");
  });

  it("服务端登出失败（500）本地仍完成登出", async () => {
    authenticatedSession();
    server.use(
      http.post(LOGOUT_URL, () =>
        HttpResponse.json(
          {
            request_id: "req-500",
            error_code: "internal_error",
            message: "撤销失败",
          },
          { status: 500 },
        ),
      ),
    );
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
