import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE_URL } from "@/lib/api/client";
import { resetSession, setTokenRefresher } from "@/lib/api/session";
import { login, logout, refresh } from "@/features/auth/api";
import { server } from "@tests/msw/server";

const LOGIN_URL = `${API_BASE_URL}/api/v1/auth/login`;
const REFRESH_URL = `${API_BASE_URL}/api/v1/auth/refresh`;
const LOGOUT_URL = `${API_BASE_URL}/api/v1/auth/logout`;

const LOGIN_OK = {
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
};

describe("认证端点", () => {
  afterEach(() => {
    resetSession();
  });

  it("登录以携带凭据的方式发送（跨源 Cookie 依赖此开关）", async () => {
    let seen: Request | undefined;
    server.use(
      http.post(LOGIN_URL, ({ request }) => {
        seen = request;
        return HttpResponse.json(LOGIN_OK);
      }),
    );

    await login({ username: "admin", password: "secret" });

    expect(seen?.credentials).toBe("include");
  });

  it("刷新不带请求体且携带凭据（刷新令牌只在 Cookie 里）", async () => {
    let seen: Request | undefined;
    server.use(
      http.post(REFRESH_URL, ({ request }) => {
        seen = request;
        return HttpResponse.json({
          request_id: "req-refresh",
          access_token: "access-2",
          token_type: "Bearer",
          expires_in: 900,
        });
      }),
    );

    await refresh();

    expect(seen?.credentials).toBe("include");
    expect(await seen?.text()).toBe("");
  });

  it("登出不注入访问令牌（登出本身不该因令牌过期而被刷新打断）", async () => {
    let authHeader: string | null = null;
    server.use(
      http.post(LOGOUT_URL, ({ request }) => {
        authHeader = request.headers.get("Authorization");
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await logout();

    expect(authHeader).toBeNull();
  });

  it("认证端点自身的 401 不触发刷新重放（避免请求自等待）", async () => {
    const refresher = vi.fn(async () => "new-token");
    setTokenRefresher(refresher);
    let calls = 0;
    server.use(
      http.post(REFRESH_URL, () => {
        calls += 1;
        return HttpResponse.json(
          {
            request_id: "req-refresh-401",
            error_code: "unauthorized",
            message: "刷新令牌无效",
          },
          { status: 401 },
        );
      }),
    );

    await expect(refresh()).rejects.toMatchObject({ status: 401 });

    expect(refresher).not.toHaveBeenCalled();
    // 只发一次：没有重放
    expect(calls).toBe(1);
  });
});
