import { create } from "zustand";

import type { UserSummary } from "@/types/api";

/**
 * 会话状态。
 *
 * `unknown` 是"尚未完成恢复"——守卫据此渲染加载态而不是登录页，
 * 避免受保护内容闪现（design F1/F3）。
 * `bootstrap_error` 与 `anonymous` 必须分开：「我没登录」和「服务挂了」
 * 对 users 是完全不同的信息，前者去登录页，后者要能重试（design F6）。
 * 访问令牌不进 store：它由 `lib/api/session.ts` 以模块级变量持有（design F2）。
 */
export type SessionStatus =
  | "unknown"
  | "authenticated"
  | "anonymous"
  | "bootstrap_error";

interface SessionState {
  status: SessionStatus;
  user: UserSummary | null;
  /** 引导失败（非 401）时的可读提示，供重试界面展示 */
  bootstrapError: string | null;
  /** 登录或引导成功后进入已登录态并记下账号 */
  applyAuthenticated: (user: UserSummary) => void;
  /** 会话不可用（登出、刷新令牌失效、账号查询被拒） */
  applyAnonymous: () => void;
  /** 引导因网络/服务端故障失败（区别于"未登录"） */
  applyBootstrapError: (message: string) => void;
  /** 回到未知态（测试隔离与重新引导） */
  reset: () => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  status: "unknown",
  user: null,
  bootstrapError: null,
  applyAuthenticated: (user) =>
    set({ status: "authenticated", user, bootstrapError: null }),
  applyAnonymous: () => set({ status: "anonymous", user: null, bootstrapError: null }),
  applyBootstrapError: (message) =>
    set({ status: "bootstrap_error", user: null, bootstrapError: message }),
  reset: () => set({ status: "unknown", user: null, bootstrapError: null }),
}));
