import { ApiError } from "@/lib/api/errors";
import { setAccessToken } from "@/lib/api/session";

import { refresh } from "./api";

/**
 * 刷新失败的原因。
 *
 * 两类失败的处理**完全不同**（design.md「状态码 503 的处理」）：
 * - `invalid`：刷新令牌失效/被撤销 → 登录态真的没了 → 置匿名并跳登录页
 * - `transient`：后端撤销能力不可用（503）或网络错误 → 只是暂时拿不到新令牌，
 *   **不得把用户踢出去**，按普通错误提示即可
 */
export type RefreshFailure = "invalid" | "transient";

let lastFailure: RefreshFailure | null = null;

/** 取走并清空上一次刷新失败的原因（一次失败只被消费一次） */
export function consumeRefreshFailure(): RefreshFailure | null {
  const failure = lastFailure;
  lastFailure = null;
  return failure;
}

/**
 * 请求层使用的刷新实现。
 *
 * 契约来自 `session.ts` 的 `TokenRefresher`：成功返回新令牌，**失败返回 null
 * 而不抛异常**（抛异常会让"刷新失败"散落到每个调用点）。失败原因另由
 * `consumeRefreshFailure()` 提供——`session.ts` 的接口只容得下一个 null。
 */
export async function refreshSessionToken(): Promise<string | null> {
  try {
    const response = await refresh();
    if (!response.access_token) {
      lastFailure = "invalid";
      setAccessToken(null);
      return null;
    }
    lastFailure = null;
    setAccessToken(response.access_token);
    return response.access_token;
  } catch (error) {
    lastFailure =
      error instanceof ApiError && error.status === 401 ? "invalid" : "transient";
    setAccessToken(null);
    return null;
  }
}
