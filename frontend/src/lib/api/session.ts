/**
 * 访问令牌与刷新动作的持有者。
 *
 * 真实的登录/刷新在 auth change 中接入：本 change 只提供**机制**——
 * 令牌注入、401 刷新重放（刷新动作以单例 Promise 收敛）、刷新失败后的回调。
 */

/** 刷新令牌的实现，由 auth 层注入（返回新的访问令牌，失败返回 null） */
export type TokenRefresher = () => Promise<string | null>;

/** 刷新失败后的处理（通常是跳转登录页） */
export type AuthFailureHandler = () => void;

let accessToken: string | null = null;
let refreshPromise: Promise<string | null> | null = null;
let refresher: TokenRefresher | null = null;
let authFailureHandler: AuthFailureHandler | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function setTokenRefresher(fn: TokenRefresher | null): void {
  refresher = fn;
}

export function setAuthFailureHandler(fn: AuthFailureHandler | null): void {
  authFailureHandler = fn;
}

/**
 * 刷新访问令牌。
 *
 * 并发调用共享同一个 Promise：多个请求同时收到 401 时只刷新一次。
 */
export function refreshAccessToken(): Promise<string | null> {
  refreshPromise ??= runRefresher();
  return refreshPromise;
}

async function runRefresher(): Promise<string | null> {
  try {
    const next = refresher ? await refresher() : null;
    accessToken = next;
    return next;
  } catch {
    accessToken = null;
    return null;
  } finally {
    refreshPromise = null;
  }
}

/** 刷新失败时通知上层（跳转登录） */
export function notifyAuthFailure(): void {
  authFailureHandler?.();
}

/** 清空会话状态（登出，或测试之间隔离） */
export function resetSession(): void {
  accessToken = null;
  refreshPromise = null;
  refresher = null;
  authFailureHandler = null;
}
