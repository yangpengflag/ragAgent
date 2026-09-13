import { setupServer } from "msw/node";

import { handlers } from "./handlers";

/** 所有 HTTP 交互都由 msw 拦截，测试不依赖真实后端 */
export const server = setupServer(...handlers);
