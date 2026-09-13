import { ApiError } from "@/lib/api/errors";
import { setAccessToken } from "@/lib/api/session";

import { fetchCurrentUser, refresh } from "./api";
import { useSessionStore } from "./session-store";

/**
 * 启动引导：refresh → me 两步（design F1）。
 *
 * 刷新接口不返回账号，所以必须先换令牌再查账号。
 * 失败分类是这里的重点：
 * - 401 → 匿名（刷新令牌失效 / 账号被停用），正常去登录页
 * - 其它（网络错误、5xx）→ 引导失败态，可重试，**不静默当作未登录**
 */
/**
 * 进行中的引导（并发去重）。
 *
 * 必须去重：`main.tsx` 使用 StrictMode，effect 会"挂载→清理→再挂载"，
 * 而刷新令牌是**轮换制**——两次并发刷新会互相作废，表现为偶发被踢回登录页。
 * 结束后清空：引导失败要能重试（守卫的重试按钮依赖这一点）。
 */
let inFlight: Promise<void> | null = null;

export function bootstrapSession(): Promise<void> {
  inFlight ??= runBootstrap().finally(() => {
    inFlight = null;
  });
  return inFlight;
}

async function runBootstrap(): Promise<void> {
  try {
    const refreshed = await refresh();
    setAccessToken(refreshed.access_token);
    const me = await fetchCurrentUser();
    useSessionStore.getState().applyAuthenticated(me.user);
  } catch (error) {
    setAccessToken(null);
    if (error instanceof ApiError && error.status === 401) {
      useSessionStore.getState().applyAnonymous();
      return;
    }
    useSessionStore.getState().applyBootstrapError(readableMessage(error));
  }
}

function readableMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message || "服务暂时不可用，请稍后重试";
  }
  return "无法连接到服务器，请确认网络或后端服务状态";
}
