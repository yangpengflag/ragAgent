import { setTokenRefresher } from "@/lib/api/session";

import { refreshSessionToken } from "./token-refresher";

/**
 * 应用级接线：把真实的刷新实现交给请求层。
 *
 * 只做"注入"，不做副作用判断——刷新失败后的跳转由 `session.ts` 的
 * `notifyAuthFailure` 统一触发（本 change 任务 1.10 把处理器注册点上也移到这里）。
 */
export function wireTokenRefresher(): void {
  setTokenRefresher(refreshSessionToken);
}
