import { useSessionStore } from "./session-store";
import { consumeRefreshFailure } from "./token-refresher";

/** 跳转函数的窄接口：只依赖"去某处"，便于单测注入替身 */
export type NavigateTo = (to: string, options?: { replace?: boolean }) => void;

/**
 * 刷新失败后的处理：清会话 + 跳登录页。
 *
 * 会话状态必须**在这里**显式置为匿名：跳转只是路由结果，
 * 若只跳转不清状态，守卫仍可能认为"仍在恢复中"而闪现内容（design F6）。
 *
 * 例外：`transient` 类失败（后端撤销能力 503 / 网络错误）不是"登录态失效"，
 * 此时既不置匿名也不跳登录——把人踢到登录页会让一次后端抖动变成用户可见的登出。
 * 错误本身由请求层抛给调用方，按普通错误提示即可。
 */
export function createAuthFailureHandler(navigate: NavigateTo): () => void {
  return () => {
    if (consumeRefreshFailure() === "transient") {
      return;
    }
    useSessionStore.getState().applyAnonymous();
    navigate("/login", { replace: true });
  };
}
