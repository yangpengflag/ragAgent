import { setAccessToken } from "@/lib/api/session";

import { logout } from "./api";
import { useSessionStore } from "./session-store";

/**
 * 登出：本地会话**先清**，服务端撤销失败只告警（design F6）。
 *
 * 顺序不能反：登出是用户表达"我要离开"的意图，后端或网络问题
 * 不能把人困在界面里。所以无论接口成功与否，本地都完成登出，
 * 剩余的差异只是"服务端是否也撤销了刷新令牌"。
 */
export async function performLogout(): Promise<void> {
  try {
    await logout();
  } catch {
    // 服务端撤销失败（含 503）：只告警，不改变本地已登出的事实
  } finally {
    setAccessToken(null);
    useSessionStore.getState().applyAnonymous();
  }
}
