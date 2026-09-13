import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";

import { API_BASE_URL } from "@/lib/api/client";
import { getAccessToken, resetSession, setAccessToken } from "@/lib/api/session";
import {
  consumeRefreshFailure,
  refreshSessionToken,
} from "@/features/auth/token-refresher";
import { server } from "@tests/msw/server";

const REFRESH_URL = `${API_BASE_URL}/api/v1/auth/refresh`;

function refreshOk(token: string) {
  return http.post(REFRESH_URL, () =>
    HttpResponse.json({
      request_id: "req-refresh",
      access_token: token,
      token_type: "Bearer",
      expires_in: 900,
    }),
  );
}

function refreshFailed(status: number, errorCode: string) {
  return http.post(REFRESH_URL, () =>
    HttpResponse.json(
      {
        request_id: "req-refresh-fail",
        error_code: errorCode,
        message: "刷新令牌无效",
      },
      { status },
    ),
  );
}

describe("刷新实现", () => {
  afterEach(() => {
    resetSession();
  });

  it("成功时更新内存中的访问令牌并返回令牌", async () => {
    server.use(refreshOk("new-token"));

    const token = await refreshSessionToken();

    expect(token).toBe("new-token");
    expect(getAccessToken()).toBe("new-token");
  });

  it("刷新令牌失效时返回 null 且不抛异常", async () => {
    server.use(refreshFailed(401, "unauthorized"));
    setAccessToken("stale-token");

    await expect(refreshSessionToken()).resolves.toBeNull();
    // 失效后不得继续携带旧令牌
    expect(getAccessToken()).toBeNull();
    // 归类为"登录态失效"：失败处理器据此跳登录页
    expect(consumeRefreshFailure()).toBe("invalid");
  });

  it("服务端不可用（503）返回 null 但归类为暂时性失败（不登出）", async () => {
    server.use(refreshFailed(503, "upstream_unavailable"));

    await expect(refreshSessionToken()).resolves.toBeNull();
    expect(consumeRefreshFailure()).toBe("transient");
  });
});
