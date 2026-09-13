import { render, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { StrictMode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { API_BASE_URL } from "@/lib/api/client";
import { getAccessToken, resetSession } from "@/lib/api/session";
import { bootstrapSession } from "@/features/auth/bootstrap";
import { useSessionStore } from "@/features/auth/session-store";
import { SessionBootstrap } from "@/features/auth/SessionBootstrap";
import { server } from "@tests/msw/server";

const REFRESH_URL = `${API_BASE_URL}/api/v1/auth/refresh`;
const ME_URL = `${API_BASE_URL}/api/v1/auth/me`;

const ACCOUNT = {
  id: "01936b2a-0000-7000-8000-000000000001",
  username: "admin",
  display_name: "系统管理员",
  system_role: "ADMIN",
};

function jsonError(status: number, errorCode: string) {
  return HttpResponse.json(
    { request_id: "req-x", error_code: errorCode, message: "失败" },
    { status },
  );
}

describe("启动会话引导", () => {
  afterEach(() => {
    resetSession();
    useSessionStore.getState().reset();
  });

  it("存在有效会话时完成引导：已登录且持有账号与令牌", async () => {
    server.use(
      http.post(REFRESH_URL, () =>
        HttpResponse.json({
          request_id: "req-r",
          access_token: "fresh-token",
          token_type: "Bearer",
          expires_in: 900,
        }),
      ),
      http.get(ME_URL, () =>
        HttpResponse.json({ request_id: "req-m", user: ACCOUNT }),
      ),
    );

    await bootstrapSession();

    expect(useSessionStore.getState().status).toBe("authenticated");
    expect(useSessionStore.getState().user).toEqual(ACCOUNT);
    expect(getAccessToken()).toBe("fresh-token");
  });

  it("重复/并发引导只发一次刷新（StrictMode 双调用安全）", async () => {
    let calls = 0;
    server.use(
      http.post(REFRESH_URL, () => {
        calls += 1;
        return HttpResponse.json({
          request_id: "req-r",
          access_token: "fresh-token",
          token_type: "Bearer",
          expires_in: 900,
        });
      }),
      http.get(ME_URL, () =>
        HttpResponse.json({ request_id: "req-m", user: ACCOUNT }),
      ),
    );

    // StrictMode 下 effect 会执行一次清理再执行：刷新接口是**轮换制**，
    // 两次并发刷新会互相作废，表现为"偶发被踢回登录页"
    render(
      <StrictMode>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <SessionBootstrap />
        </MemoryRouter>
      </StrictMode>,
    );

    await waitFor(() => {
      expect(useSessionStore.getState().status).toBe("authenticated");
    });
    expect(calls).toBe(1);
  });

  it("引导失败后可以重试（不被去重逻辑锁死）", async () => {
    server.use(http.post(REFRESH_URL, () => jsonError(503, "upstream_unavailable")));
    await bootstrapSession();
    expect(useSessionStore.getState().status).toBe("bootstrap_error");

    server.use(
      http.post(REFRESH_URL, () =>
        HttpResponse.json({
          request_id: "req-r2",
          access_token: "fresh-token",
          token_type: "Bearer",
          expires_in: 900,
        }),
      ),
      http.get(ME_URL, () =>
        HttpResponse.json({ request_id: "req-m", user: ACCOUNT }),
      ),
    );
    await bootstrapSession();

    expect(useSessionStore.getState().status).toBe("authenticated");
  });

  it("刷新令牌无效（401）→ 匿名态，不当作服务故障", async () => {
    server.use(http.post(REFRESH_URL, () => jsonError(401, "unauthorized")));

    await bootstrapSession();

    expect(useSessionStore.getState().status).toBe("anonymous");
    expect(useSessionStore.getState().bootstrapError).toBeNull();
  });

  it("服务不可用（非 401）→ 引导失败态并给出可展示的错误（可重试）", async () => {
    server.use(http.post(REFRESH_URL, () => jsonError(503, "upstream_unavailable")));

    await bootstrapSession();

    expect(useSessionStore.getState().status).toBe("bootstrap_error");
    expect(useSessionStore.getState().bootstrapError).toBeTruthy();
  });

  it("刷新成功但账号查询 401 → 匿名态（账号被停用等）", async () => {
    server.use(
      http.post(REFRESH_URL, () =>
        HttpResponse.json({
          request_id: "req-r",
          access_token: "fresh-token",
          token_type: "Bearer",
          expires_in: 900,
        }),
      ),
      http.get(ME_URL, () => jsonError(401, "unauthorized")),
    );

    await bootstrapSession();

    expect(useSessionStore.getState().status).toBe("anonymous");
    expect(useSessionStore.getState().user).toBeNull();
  });
});
