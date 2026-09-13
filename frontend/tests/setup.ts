import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

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
});

afterAll(() => {
  server.close();
});
