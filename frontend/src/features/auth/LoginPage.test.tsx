import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, delay, http } from "msw";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { API_BASE_URL } from "@/lib/api/client";
import { getAccessToken, resetSession } from "@/lib/api/session";
import { LoginPage } from "@/features/auth/LoginPage";
import { useSessionStore } from "@/features/auth/session-store";
import { server } from "@tests/msw/server";

const LOGIN_URL = `${API_BASE_URL}/api/v1/auth/login`;
const ACCOUNT = {
  id: "01936b2a-0000-7000-8000-000000000001",
  username: "admin",
  display_name: "系统管理员",
  system_role: "ADMIN",
};

function loginOk() {
  return HttpResponse.json({
    request_id: "req-login",
    access_token: "access-1",
    token_type: "Bearer",
    expires_in: 900,
    user: ACCOUNT,
  });
}

/** 用真实路由渲染：跳转结果由落地页是否出现来断言，不给组件加测试专用 prop */
function renderLoginPage() {
  return render(
    <MemoryRouter
      initialEntries={["/login"]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<div>受保护落地页</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

async function fill(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("用户名"), "admin");
  await user.type(screen.getByLabelText("密码"), "secret");
}

describe("登录页", () => {
  afterEach(() => {
    resetSession();
    useSessionStore.getState().reset();
  });

  it("登录成功：进入应用并持有账号与令牌", async () => {
    server.use(http.post(LOGIN_URL, () => loginOk()));
    const user = userEvent.setup();
    renderLoginPage();

    await fill(user);
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("受保护落地页")).toBeInTheDocument();
    expect(useSessionStore.getState().status).toBe("authenticated");
    expect(useSessionStore.getState().user).toEqual(ACCOUNT);
    expect(getAccessToken()).toBe("access-1");
  });

  it("凭据错误：提示可读且不区分账号是否存在，表单可再次提交", async () => {
    server.use(
      http.post(LOGIN_URL, () =>
        HttpResponse.json(
          {
            request_id: "req-401",
            error_code: "unauthorized",
            message: "用户名或密码错误",
          },
          { status: 401 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderLoginPage();

    await fill(user);
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("用户名或密码错误");
    expect(screen.getByRole("button", { name: "登录" })).toBeEnabled();
  });

  it("提交中禁止重复提交（只发一次请求）", async () => {
    let calls = 0;
    server.use(
      http.post(LOGIN_URL, async () => {
        calls += 1;
        await delay(80);
        return loginOk();
      }),
    );
    const user = userEvent.setup();
    renderLoginPage();

    await fill(user);
    const button = screen.getByRole("button", { name: /登录/ });
    await user.click(button);
    await user.click(button);

    await waitFor(() => {
      expect(useSessionStore.getState().status).toBe("authenticated");
    });
    expect(calls).toBe(1);
  });

  it("网络或服务端故障：展示可读错误并可重试", async () => {
    server.use(
      http.post(LOGIN_URL, () =>
        HttpResponse.json(
          {
            request_id: "req-500",
            error_code: "internal_error",
            message: "数据库连接失败",
          },
          { status: 500 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderLoginPage();

    await fill(user);
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("数据库连接失败");
    expect(screen.getByRole("button", { name: "登录" })).toBeEnabled();
  });

  it("响应体不可读（网络错误）：仍有可读兜底文案", async () => {
    // msw 的 HttpResponse.error() 模拟连接层失败：前端读不到任何响应体
    server.use(http.post(LOGIN_URL, () => HttpResponse.error()));
    const user = userEvent.setup();
    renderLoginPage();

    await fill(user);
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("无法连接到服务器");
  });

  it("响应体不可读（500 空响应体）：按状态码兜底，不依赖 error_code", async () => {
    server.use(
      http.post(LOGIN_URL, () => new HttpResponse(null, { status: 500 })),
    );
    const user = userEvent.setup();
    renderLoginPage();

    await fill(user);
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("请求失败（HTTP 500）");
  });

  it("被限流（429）：展示限流提示且表单仍可提交", async () => {
    server.use(
      http.post(LOGIN_URL, () =>
        HttpResponse.json(
          {
            request_id: "req-429",
            error_code: "rate_limited",
            message: "请求过于频繁",
          },
          { status: 429 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderLoginPage();

    await fill(user);
    await user.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("尝试过于频繁");
    expect(screen.getByRole("button", { name: "登录" })).toBeEnabled();
  });
});
