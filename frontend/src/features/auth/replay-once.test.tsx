import { render, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";

import { AppProviders } from "@/app/providers";
import { apiFetch, API_BASE_URL } from "@/lib/api/client";
import { getAccessToken, resetSession, setAccessToken } from "@/lib/api/session";
import { server } from "@tests/msw/server";

const HEALTH_URL = `${API_BASE_URL}/api/v1/health`;
const REFRESH_URL = `${API_BASE_URL}/api/v1/auth/refresh`;

const HEALTH_OK = {
  request_id: "req-health",
  status: "ok",
  components: {
    mysql: { status: "ok", error: null },
    redis: { status: "ok", error: null },
    milvus: { status: "ok", error: null },
  },
};

/**
 * 用**真实刷新实现**复验「401 → 刷新 → 重放一次」。
 *
 * 刷新实现由 `AppProviders` 接线（应用里也是这条路径），
 * 不再注入 `async () => "token"` 这类假 refresher——否则测的是机制而不是接线。
 */
describe("401 → 刷新 → 重放一次", () => {
  afterEach(() => {
    resetSession();
  });

  it("业务请求遇 401 后刷新并重放，调用方得到成功结果", async () => {
    render(<AppProviders>{null}</AppProviders>);
    setAccessToken("expired-token");

    let calls = 0;
    server.use(
      http.get(HEALTH_URL, () => {
        calls += 1;
        if (calls === 1) {
          return HttpResponse.json(
            {
              request_id: "req-401",
              error_code: "token_expired",
              message: "令牌已过期",
            },
            { status: 401 },
          );
        }
        return HttpResponse.json(HEALTH_OK);
      }),
      http.post(REFRESH_URL, () =>
        HttpResponse.json({
          request_id: "req-refresh",
          access_token: "fresh-token",
          token_type: "Bearer",
          expires_in: 900,
        }),
      ),
    );

    const data = await apiFetch<typeof HEALTH_OK>("/api/v1/health");

    expect(data.status).toBe("ok");
    expect(calls).toBe(2);
    expect(getAccessToken()).toBe("fresh-token");
  });

  it("刷新失败时重放不再发生（只发一次请求）", async () => {
    render(<AppProviders>{null}</AppProviders>);
    setAccessToken("expired-token");

    let calls = 0;
    server.use(
      http.get(HEALTH_URL, () => {
        calls += 1;
        return HttpResponse.json(
          {
            request_id: "req-401",
            error_code: "token_expired",
            message: "令牌已过期",
          },
          { status: 401 },
        );
      }),
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

    await expect(apiFetch("/api/v1/health")).rejects.toMatchObject({ status: 401 });
    await waitFor(() => {
      expect(calls).toBe(1);
    });
  });
});
