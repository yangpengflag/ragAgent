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
    const refreshed = await refreshAccessToken();
    if (refreshed === null) {
      notifyAuthFailure();
      throw await toApiError(response);
    }
    // 重放一次：失败不再重放，避免刷新→401→刷新 的死循环
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

/** 服务端未给出 `error_code` 时的兜底（与后端语义保持一致） */
function fallbackErrorCode(status: number): string {
  if (status >= 500) {
    return "internal_error";
  }
  if (status === 401) {
    return "unauthorized";
  }
  if (status === 403) {
    return "access_denied";
  }
  if (status === 404) {
    return "not_found";
  }
  return "bad_request";
}
