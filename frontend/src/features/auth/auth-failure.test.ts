import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE_URL } from "@/lib/api/client";
import {
  getAccessToken,
  resetSession,
  setAccessToken,
  setAuthFailureHandler,
  setTokenRefresher,
} from "@/lib/api/session";
import { createAuthFailureHandler } from "@/features/auth/auth-failure";
import { useSessionStore } from "@/features/auth/session-store";
import { refreshSessionToken } from "@/features/auth/token-refresher";
import { server } from "@tests/msw/server";

const ME_URL = `${API_BASE_URL}/api/v1/auth/me`;
const REFRESH_URL = `${API_BASE_URL}/api/v1/auth/refresh`;

function unauthorized() {
  return HttpResponse.json(
    { request_id: "req-401", error_code: "unauthorized", message: "未认证" },
    { status: 401 },
  );
}

describe("刷新失败后的会话收敛", () => {
  afterEach(() => {
    resetSession();
    useSessionStore.getState().reset();
  });

  it("刷新失败 → 会话置为匿名并跳转登录页", async () => {
    const navigate = vi.fn();
    setAuthFailureHandler(createAuthFailureHandler(navigate));
    setTokenRefresher(async () => null);
    setAccessToken("stale-token");

    server.use(http.get(ME_URL, () => unauthorized()));

    const { apiFetch } = await import("@/lib/api/client");
    await expect(apiFetch(ME_URL.replace(API_BASE_URL, ""))).rejects.toMatchObject({
      status: 401,
    });

    expect(useSessionStore.getState().status).toBe("anonymous");
    expect(navigate).toHaveBeenCalledWith("/login", { replace: true });
  });

  it("刷新遇到 503（后端撤销能力不可用）不登出、不跳登录页", async () => {
    const navigate = vi.fn();
    setAuthFailureHandler(createAuthFailureHandler(navigate));
    // 用真实刷新实现：分类逻辑由它给出，而不是靠注入的假 refresher
    setTokenRefresher(refreshSessionToken);
    useSessionStore.getState().applyAuthenticated({
      id: "01936b2a-0000-7000-8000-000000000001",
      username: "admin",
      display_name: "系统管理员",
      system_role: "ADMIN",
    });
    setAccessToken("token");

    server.use(
      http.get(ME_URL, () => unauthorized()),
      http.post(REFRESH_URL, () =>
        HttpResponse.json(
          {
            request_id: "req-503",
            error_code: "upstream_unavailable",
            message: "撤销服务不可用",
          },
          { status: 503 },
        ),
      ),
    );

    const { apiFetch } = await import("@/lib/api/client");
    await expect(apiFetch("/api/v1/auth/me")).rejects.toBeTruthy();

    expect(navigate).not.toHaveBeenCalled();
    // 仍然保持已登录：503 是后端暂时不可用，不是"我没登录"
    expect(useSessionStore.getState().status).toBe("authenticated");
  });

  it("刷新失败后不再携带旧访问令牌", async () => {
    const navigate = vi.fn();
    setAuthFailureHandler(createAuthFailureHandler(navigate));
    setTokenRefresher(async () => null);
    setAccessToken("stale-token");

    const seen: (string | null)[] = [];
    server.use(
      http.get(ME_URL, ({ request }) => {
        seen.push(request.headers.get("Authorization"));
        return unauthorized();
      }),
      http.post(REFRESH_URL, () => unauthorized()),
    );

    const { apiFetch } = await import("@/lib/api/client");
    await expect(apiFetch("/api/v1/auth/me")).rejects.toMatchObject({ status: 401 });
    expect(getAccessToken()).toBeNull();

    // 失败之后的新请求：不得再挂旧令牌
    await expect(apiFetch("/api/v1/auth/me")).rejects.toMatchObject({ status: 401 });
    expect(seen.at(-1)).toBeNull();
  });
});
