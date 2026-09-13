import type { ApiErrorBody } from "@/types/api";

import { ApiError } from "./errors";
import { getAccessToken, notifyAuthFailure, refreshAccessToken } from "./session";

/**
 * API 基址：来自 `VITE_API_BASE_URL`，默认本地后端 8000 端口。
 */
export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

export interface RequestOptions extends Omit<RequestInit, "body"> {
  /** 请求体（对象会被 JSON 序列化） */
  body?: unknown;
  /** 是否注入访问令牌（默认注入） */
  auth?: boolean;
  /** 内部使用：401 重放时置 false，避免无限重放 */
  replayOn401?: boolean;
}

/**
 * 统一请求入口。
 *
 * 职责：拼基址、注入 Bearer 令牌、401 刷新后**重放一次**、错误归一化为 `ApiError`。
 * 业务 API 函数只声明路径与参数，不重复这些样板。
 */
export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { body, auth = true, replayOn401 = true, headers, ...rest } = options;

  const token = auth ? getAccessToken() : null;
  const requestHeaders: Record<string, string> = {
    Accept: "application/json",
    ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    ...(token === null ? {} : { Authorization: `Bearer ${token}` }),
    ...(headers as Record<string, string> | undefined),
  };

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers: requestHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    throw new ApiError({
      status: 0,
      request_id: "",
      error_code: "network_error",
      message: "无法连接到服务器，请确认后端服务已启动",
      cause,
    });
  }

  if (response.status === 401 && auth && replayOn401) {
    // 若本次请求飞行期间令牌已被其他请求刷新过，直接重放即可，
    // 不再触发第二次刷新（错峰 401 场景）。
    const tokenWasRefreshed = getAccessToken() !== token;
    if (!tokenWasRefreshed) {
      const refreshed = await refreshAccessToken();
      if (refreshed === null) {
        notifyAuthFailure();
        throw await toApiError(response);
      }
    }
    // 释放未消费的 401 响应体，再重放一次（失败不再重放，避免死循环）
    await discard(response);
    return apiFetch<T>(path, { ...options, replayOn401: false });
  }

  if (!response.ok) {
    throw await toApiError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function toApiError(response: Response): Promise<ApiError> {
  const body = await readJsonBody(response);
  return new ApiError({
    status: response.status,
    request_id: readString(body?.request_id),
    error_code: readString(body?.error_code) || fallbackErrorCode(response.status),
    message:
      readString(body?.message) || `请求失败（HTTP ${response.status}）`,
    details: body?.details,
  });
}

async function readJsonBody(
  response: Response,
): Promise<Partial<ApiErrorBody> | null> {
  try {
    const parsed: unknown = await response.json();
    if (parsed !== null && typeof parsed === "object") {
      return parsed as Partial<ApiErrorBody>;
    }
    return null;
  } catch {
    return null;
  }
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

async function discard(response: Response): Promise<void> {
  try {
    await response.text();
  } catch {
    // 仅为释放响应体，忽略任何读取失败
  }
}

/**
 * 服务端未给出 `error_code` 时的兜底。
 *
 * 与后端 `.codebuddy/rules/api-conventions.md` 的错误码表逐条对齐
 * （后端 `error_handlers.py::_error_code_for_status` 是同一张表），
 * 保证调用方按 `error_code` 分支时不会因来源不同而误判。
 */
const FALLBACK_ERROR_CODES: Record<number, string> = {
  400: "bad_request",
  401: "unauthorized",
  403: "access_denied",
  404: "not_found",
  405: "method_not_allowed",
  409: "conflict",
  413: "file_too_large",
  415: "unsupported_file_type",
  422: "validation_error",
  429: "rate_limited",
  503: "upstream_unavailable",
};

function fallbackErrorCode(status: number): string {
  const mapped = FALLBACK_ERROR_CODES[status];
  if (mapped !== undefined) {
    return mapped;
  }
  return status >= 500 ? "internal_error" : "bad_request";
}
