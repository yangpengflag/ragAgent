import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { API_BASE_URL, apiFetch } from "@/lib/api/client";
import { isApiError } from "@/lib/api/errors";
import {
  setAccessToken,
  setAuthFailureHandler,
  setTokenRefresher,
} from "@/lib/api/session";

import { server } from "@tests/msw/server";

const ECHO_URL = `${API_BASE_URL}/api/v1/echo`;

describe("API 客户端", () => {
  it("已持有令牌时注入 Authorization 头", async () => {
    setAccessToken("access-token-1");
    let seen: string | null = null;
    server.use(
      http.get(ECHO_URL, ({ request }) => {
        seen = request.headers.get("authorization");
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiFetch("/api/v1/echo");

    expect(seen).toBe("Bearer access-token-1");
  });

  it("未持有令牌时不注入 Authorization 头", async () => {
    let seen: string | null = "unset";
    server.use(
      http.get(ECHO_URL, ({ request }) => {
        seen = request.headers.get("authorization");
        return HttpResponse.json({ ok: true });
      }),
    );

    await apiFetch("/api/v1/echo");

    expect(seen).toBeNull();
  });

  it("服务端错误被归一化为 ApiError，字段名与后端一致", async () => {
    server.use(
      http.post(ECHO_URL, () =>
        HttpResponse.json(
          {
            request_id: "req-1",
            error_code: "validation_error",
            message: "参数不合法",
            details: { field: "name" },
          },
          { status: 422 },
        ),
      ),
    );

    const error: unknown = await apiFetch("/api/v1/echo", {
      method: "POST",
    }).catch((caught: unknown) => caught);

    expect(isApiError(error)).toBe(true);
    if (!isApiError(error)) {
      throw new Error("应抛出 ApiError");
    }
    expect(error.request_id).toBe("req-1");
    expect(error.error_code).toBe("validation_error");
    expect(error.message).toBe("参数不合法");
    expect(error.status).toBe(422);
    expect(error.details).toEqual({ field: "name" });
  });

  it("网络不可达时归一化为 network_error", async () => {
    server.use(http.get(ECHO_URL, () => HttpResponse.error()));

    const error: unknown = await apiFetch("/api/v1/echo").catch(
      (caught: unknown) => caught,
    );

    expect(isApiError(error)).toBe(true);
    if (!isApiError(error)) {
      throw new Error("应抛出 ApiError");
    }
    expect(error.error_code).toBe("network_error");
    expect(error.status).toBe(0);
  });

  it("401 且刷新有效时自动刷新并重放一次", async () => {
    setAccessToken("expired-token");
    const seenAuth: string[] = [];
    server.use(
      http.get(ECHO_URL, ({ request }) => {
        const auth = request.headers.get("authorization") ?? "";
        seenAuth.push(auth);
        if (auth === "Bearer expired-token") {
          return HttpResponse.json(
            {
              request_id: "req-401",
              error_code: "unauthorized",
              message: "令牌已过期",
            },
            { status: 401 },
          );
        }
        return HttpResponse.json({ ok: true });
      }),
    );
    const refresher = vi.fn(async () => "fresh-token");
    setTokenRefresher(refresher);

    const result = await apiFetch<{ ok: boolean }>("/api/v1/echo");

    expect(result.ok).toBe(true);
    expect(refresher).toHaveBeenCalledTimes(1);
    expect(seenAuth).toEqual(["Bearer expired-token", "Bearer fresh-token"]);
  });

  it("并发 401 只触发一次刷新", async () => {
    setAccessToken("expired-token");
    server.use(
      http.get(ECHO_URL, ({ request }) => {
        const auth = request.headers.get("authorization") ?? "";
        if (auth === "Bearer expired-token") {
          return HttpResponse.json(
            {
              request_id: "req-401",
              error_code: "unauthorized",
              message: "令牌已过期",
            },
            { status: 401 },
          );
        }
        return HttpResponse.json({ ok: true });
      }),
    );
    const refresher = vi.fn(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
      return "fresh-token";
    });
    setTokenRefresher(refresher);

    await Promise.all([apiFetch("/api/v1/echo"), apiFetch("/api/v1/echo")]);

    expect(refresher).toHaveBeenCalledTimes(1);
  });

  it("刷新失败时跳转登录且不重放原请求", async () => {
    setAccessToken("expired-token");
    let requestCount = 0;
    server.use(
      http.get(ECHO_URL, () => {
        requestCount += 1;
        return HttpResponse.json(
          {
            request_id: "req-401",
            error_code: "unauthorized",
            message: "令牌已过期",
          },
          { status: 401 },
        );
      }),
    );
    const onAuthFailure = vi.fn();
    setAuthFailureHandler(onAuthFailure);
    setTokenRefresher(async () => null);

    const error: unknown = await apiFetch("/api/v1/echo").catch(
      (caught: unknown) => caught,
    );

    expect(isApiError(error)).toBe(true);
    if (!isApiError(error)) {
      throw new Error("应抛出 ApiError");
    }
    expect(error.error_code).toBe("unauthorized");
    expect(onAuthFailure).toHaveBeenCalledTimes(1);
    expect(requestCount).toBe(1);
  });

  it("并发 401 且刷新失败时，登录跳转只通知一次", async () => {
    setAccessToken("expired-token");
    server.use(
      http.get(ECHO_URL, () =>
        HttpResponse.json(
          {
            request_id: "req-401",
            error_code: "unauthorized",
            message: "令牌已过期",
          },
          { status: 401 },
        ),
      ),
    );
    const onAuthFailure = vi.fn();
    setAuthFailureHandler(onAuthFailure);
    setTokenRefresher(async () => null);

    await Promise.all([
      apiFetch("/api/v1/echo").catch(() => undefined),
      apiFetch("/api/v1/echo").catch(() => undefined),
      apiFetch("/api/v1/echo").catch(() => undefined),
    ]);

    expect(onAuthFailure).toHaveBeenCalledTimes(1);
  });

  it("错峰 401：令牌已被其他请求刷新时直接重放，不再触发刷新", async () => {
    setAccessToken("expired-token");
    const refresher = vi.fn(async () => "fresh-token");
    setTokenRefresher(refresher);
    server.use(
      http.get(ECHO_URL, ({ request }) => {
        const auth = request.headers.get("authorization") ?? "";
        if (auth === "Bearer expired-token") {
          // 模拟「另一个请求已经完成刷新」后再返回 401
          setAccessToken("fresh-token");
          return HttpResponse.json(
            {
              request_id: "req-401",
              error_code: "unauthorized",
              message: "令牌已过期",
            },
            { status: 401 },
          );
        }
        return HttpResponse.json({ ok: true });
      }),
    );

    const result = await apiFetch<{ ok: boolean }>("/api/v1/echo");

    expect(result.ok).toBe(true);
    expect(refresher).not.toHaveBeenCalled();
  });

  it("刷新返回空令牌时视为刷新失败，不发出畸形请求头", async () => {
    setAccessToken("expired-token");
    server.use(
      http.get(ECHO_URL, () =>
        HttpResponse.json(
          {
            request_id: "req-401",
            error_code: "unauthorized",
            message: "令牌已过期",
          },
          { status: 401 },
        ),
      ),
    );
    const onAuthFailure = vi.fn();
    setAuthFailureHandler(onAuthFailure);
    setTokenRefresher(async () => "");

    const error: unknown = await apiFetch("/api/v1/echo").catch(
      (caught: unknown) => caught,
    );

    expect(isApiError(error)).toBe(true);
    expect(onAuthFailure).toHaveBeenCalledTimes(1);
  });

  it.each([
    [409, "conflict"],
    [413, "file_too_large"],
    [415, "unsupported_file_type"],
    [422, "validation_error"],
    [429, "rate_limited"],
    [503, "upstream_unavailable"],
    [502, "internal_error"],
  ])(
    "响应体未带 error_code 时按状态码 %i 兜底为 %s",
    async (status, expected) => {
      server.use(
        http.get(ECHO_URL, () =>
          HttpResponse.json({ message: "网关错误" }, { status }),
        ),
      );

      const error: unknown = await apiFetch("/api/v1/echo").catch(
        (caught: unknown) => caught,
      );

      expect(isApiError(error)).toBe(true);
      if (!isApiError(error)) {
        throw new Error("应抛出 ApiError");
      }
      expect(error.error_code).toBe(expected);
    },
  );
});
