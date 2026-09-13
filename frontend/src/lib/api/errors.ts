/**
 * 前端统一错误类型。
 *
 * 字段名与后端错误信封保持一致（snake_case），便于调用方按 `error_code` 分支。
 * `status === 0` 表示请求未到达服务端（网络错误）。
 */
export interface ApiErrorInit {
  status: number;
  request_id: string;
  error_code: string;
  message: string;
  details?: unknown;
  cause?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly request_id: string;
  readonly error_code: string;
  readonly details?: unknown;

  constructor(init: ApiErrorInit) {
    super(init.message, { cause: init.cause });
    this.name = "ApiError";
    this.status = init.status;
    this.request_id = init.request_id;
    this.error_code = init.error_code;
    this.details = init.details;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}
