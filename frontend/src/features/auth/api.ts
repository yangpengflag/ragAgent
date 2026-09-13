import { apiFetch } from "@/lib/api/client";
import type { LoginResponse, MeResponse, RefreshResponse } from "@/types/api";

/**
 * 认证端点。
 *
 * 三个要点（design F4/F5）：
 * - 依赖 Cookie 的接口显式声明 `credentials: "include"`（跨源携带刷新令牌）
 * - 一律 `auth: false`：这些接口本就不该携带访问令牌（登录时还没有）
 * - 一律 `replayOn401: false`：刷新是单例 Promise，若刷新接口自身的 401
 *   也走刷新重放，请求会等待"自己那个尚未 resolve 的 Promise"而永不返回
 */

export interface LoginPayload {
  username: string;
  password: string;
}

export function login(payload: LoginPayload): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/api/v1/auth/login", {
    method: "POST",
    body: payload,
    auth: false,
    replayOn401: false,
    credentials: "include",
  });
}

/** 刷新：无请求体，仅靠 Cookie。响应只给令牌，不含账号。 */
export function refresh(): Promise<RefreshResponse> {
  return apiFetch<RefreshResponse>("/api/v1/auth/refresh", {
    method: "POST",
    auth: false,
    replayOn401: false,
    credentials: "include",
  });
}

/** 登出：撤销刷新令牌并清 Cookie，幂等。 */
export function logout(): Promise<void> {
  return apiFetch<void>("/api/v1/auth/logout", {
    method: "POST",
    auth: false,
    replayOn401: false,
    credentials: "include",
  });
}

/**
 * 当前账号。
 *
 * `replayOn401: false` 是刻意的：启动引导靠这里的 401 判断"账号已不可用"
 * （如账号被停用），若交给请求层自动刷新重放，401 会被吞掉，引导无法区分
 * 「令牌刚好过期」与「账号已失效」。
 */
export function fetchCurrentUser(): Promise<MeResponse> {
  return apiFetch<MeResponse>("/api/v1/auth/me", {
    auth: true,
    replayOn401: false,
  });
}
