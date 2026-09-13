import { HttpResponse, http } from "msw";

import { API_BASE_URL } from "@/lib/api/client";
import type { UserSummary } from "@/types/api";

export const HEALTH_URL = `${API_BASE_URL}/api/v1/health`;

/** 三组件均可用 */
export const healthOkHandler = http.get(HEALTH_URL, () =>
  HttpResponse.json({
    request_id: "req-health-ok",
    status: "ok",
    components: {
      mysql: { status: "ok", error: null },
      redis: { status: "ok", error: null },
      milvus: { status: "ok", error: null },
    },
  }),
);

/** 部分组件不可用 */
export const healthDegradedHandler = http.get(HEALTH_URL, () =>
  HttpResponse.json({
    request_id: "req-health-degraded",
    status: "degraded",
    components: {
      mysql: { status: "ok", error: null },
      redis: {
        status: "down",
        error: "ConnectionError: Error 111 connecting to localhost:6379",
      },
      milvus: { status: "ok", error: null },
    },
  }),
);

/**
 * 请求失败：服务端 500。
 *
 * 以工厂形式提供，便于用例在断言「重试会重新发起请求」时统计调用次数，
 * 而不必在用例内重写一份 500 handler。
 */
export function healthFailureHandler(onRequest?: () => void) {
  return http.get(HEALTH_URL, () => {
    onRequest?.();
    return HttpResponse.json(
      {
        request_id: "req-health-500",
        error_code: "internal_error",
        message: "数据库连接失败",
      },
      { status: 500 },
    );
  });
}

/** 请求成功但没有组件数据 */
export const healthEmptyHandler = http.get(HEALTH_URL, () =>
  HttpResponse.json({
    request_id: "req-health-empty",
    status: "ok",
    components: {},
  }),
);

export const handlers = [healthOkHandler];

// ---------------------------------------------------------------- 认证

export const AUTH_URLS = {
  login: `${API_BASE_URL}/api/v1/auth/login`,
  refresh: `${API_BASE_URL}/api/v1/auth/refresh`,
  logout: `${API_BASE_URL}/api/v1/auth/logout`,
  me: `${API_BASE_URL}/api/v1/auth/me`,
} as const;

export const ACCOUNT: UserSummary = {
  id: "01936b2a-0000-7000-8000-000000000001",
  username: "admin",
  display_name: "系统管理员",
  system_role: "ADMIN",
};

/** 登录成功：下发访问令牌与账号摘要 */
export const loginSuccessHandler = http.post(AUTH_URLS.login, () =>
  HttpResponse.json({
    request_id: "req-login",
    access_token: "access-1",
    token_type: "Bearer",
    expires_in: 900,
    user: ACCOUNT,
  }),
);

/** 登录失败：凭据错误 / 限流 / 服务端故障（统一样式，便于按 error_code 分支） */
export function loginFailureHandler(
  status: number,
  errorCode: string,
  message: string,
) {
  return http.post(AUTH_URLS.login, () =>
    HttpResponse.json(
      { request_id: "req-login-fail", error_code: errorCode, message },
      { status },
    ),
  );
}

/** 刷新成功：只给令牌，不含账号 */
export const refreshSuccessHandler = http.post(AUTH_URLS.refresh, () =>
  HttpResponse.json({
    request_id: "req-refresh",
    access_token: "fresh-token",
    token_type: "Bearer",
    expires_in: 900,
  }),
);

export function refreshFailureHandler(
  status: number,
  errorCode: string,
  message = "刷新令牌无效",
) {
  return http.post(AUTH_URLS.refresh, () =>
    HttpResponse.json(
      { request_id: "req-refresh-fail", error_code: errorCode, message },
      { status },
    ),
  );
}

/** 刷新令牌无效（401）→ 登录态真的没了 */
export const refreshUnauthorizedHandler = refreshFailureHandler(
  401,
  "unauthorized",
  "刷新令牌无效",
);

/** 撤销能力不可用（503）→ 暂时性失败，不得登出 */
export const refreshUnavailableHandler = refreshFailureHandler(
  503,
  "upstream_unavailable",
  "撤销服务不可用",
);

export const logoutHandler = http.post(
  AUTH_URLS.logout,
  () => new HttpResponse(null, { status: 204 }),
);

export function logoutFailureHandler(status: number, message: string) {
  return http.post(AUTH_URLS.logout, () =>
    HttpResponse.json(
      { request_id: "req-logout-fail", error_code: "internal_error", message },
      { status },
    ),
  );
}

export const meHandler = http.get(AUTH_URLS.me, () =>
  HttpResponse.json({ request_id: "req-me", user: ACCOUNT }),
);

/** 已登录会话：引导（refresh → me）直接成功 */
export const authenticatedSessionHandlers = [
  refreshSuccessHandler,
  meHandler,
];
