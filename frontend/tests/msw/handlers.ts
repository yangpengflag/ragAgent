import { HttpResponse, http } from "msw";

import { API_BASE_URL } from "@/lib/api/client";

export const HEALTH_URL = `${API_BASE_URL}/api/v1/health`;

/** 三组件均可用 */
export const healthOkHandler = http.get(HEALTH_URL, () =>
  HttpResponse.json({
    request_id: "req-health-ok",
    status: "ok",
    components: {
      mysql: { status: "ok", error: null },
      redis: { status: "ok", error: null },
      milvus: { status: "ok", error: null },
    },
  }),
);

/** 部分组件不可用 */
export const healthDegradedHandler = http.get(HEALTH_URL, () =>
  HttpResponse.json({
    request_id: "req-health-degraded",
    status: "degraded",
    components: {
      mysql: { status: "ok", error: null },
      redis: {
        status: "down",
        error: "ConnectionError: Error 111 connecting to localhost:6379",
      },
      milvus: { status: "ok", error: null },
    },
  }),
);

/** 请求失败：服务端 500 */
export const healthFailureHandler = http.get(HEALTH_URL, () =>
  HttpResponse.json(
    {
      request_id: "req-health-500",
      error_code: "internal_error",
      message: "数据库连接失败",
    },
    { status: 500 },
  ),
);

/** 请求成功但没有组件数据 */
export const healthEmptyHandler = http.get(HEALTH_URL, () =>
  HttpResponse.json({
    request_id: "req-health-empty",
    status: "ok",
    components: {},
  }),
);

export const handlers = [healthOkHandler];
