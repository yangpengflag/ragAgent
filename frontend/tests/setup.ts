import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { useSessionStore } from "@/features/auth/session-store";
import { resetSession } from "@/lib/api/session";

import { server } from "./msw/server";

// 仅在 DOM 环境补齐 jsdom 缺失的浏览器 API（Radix 组件需要）。
// 纯 node 环境的用例（如依赖门禁）不涉及这些 API，不能无条件访问 window。
if (typeof window !== "undefined") {
  if (typeof window.matchMedia !== "function") {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  }

  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
}

beforeAll(() => {
  // 未被拦截的请求直接失败，避免测试悄悄打到真实后端
  server.listen({ onUnhandledRequest: "error" });
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetSession();
  // 会话状态是全局 store：不重置会让上一条用例的"匿名/已登录"渗到下一条，
  // 守卫据此提前跳转（表现为用例单独跑通过、整文件跑失败）
  useSessionStore.getState().reset();
});

afterAll(() => {
  server.close();
});
