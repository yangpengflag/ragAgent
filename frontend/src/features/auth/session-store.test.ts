import { beforeEach, describe, expect, it } from "vitest";

import { useSessionStore } from "@/features/auth/session-store";
import type { UserSummary } from "@/types/api";

const ACCOUNT: UserSummary = {
  id: "01936b2a-0000-7000-8000-000000000001",
  username: "admin",
  display_name: "系统管理员",
  system_role: "ADMIN",
};

describe("会话状态机", () => {
  beforeEach(() => {
    useSessionStore.getState().reset();
  });

  it("初始为未知态且不持有账号", () => {
    const state = useSessionStore.getState();

    expect(state.status).toBe("unknown");
    expect(state.user).toBeNull();
  });

  it("登录成功后为已登录并持有账号", () => {
    useSessionStore.getState().applyAuthenticated(ACCOUNT);

    const state = useSessionStore.getState();
    expect(state.status).toBe("authenticated");
    expect(state.user).toEqual(ACCOUNT);
  });

  it("登出后为匿名并清空账号", () => {
    useSessionStore.getState().applyAuthenticated(ACCOUNT);

    useSessionStore.getState().applyAnonymous();

    const state = useSessionStore.getState();
    expect(state.status).toBe("anonymous");
    expect(state.user).toBeNull();
  });

  it("重置回到未知态（测试隔离）", () => {
    useSessionStore.getState().applyAuthenticated(ACCOUNT);

    useSessionStore.getState().reset();

    expect(useSessionStore.getState().status).toBe("unknown");
  });
});
