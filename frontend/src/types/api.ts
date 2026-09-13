/**
 * 后端响应类型。
 *
 * 字段名与后端 JSON 完全一致（snake_case），**不引入大小写转换层**（见 frontend-conventions.md）。
 */

/** 统一错误信封（对应后端 `{ request_id, error_code, message, details? }`） */
export interface ApiErrorBody {
  request_id: string;
  error_code: string;
  message: string;
  details?: unknown;
}

export type HealthComponentStatus = "ok" | "down";

export interface HealthComponent {
  status: HealthComponentStatus;
  error: string | null;
}

export interface HealthResponse {
  request_id: string;
  status: "ok" | "degraded";
  components: Record<string, HealthComponent>;
}

/** 账号摘要（后端 `user` 字段：`{id, username, display_name, system_role}`） */
export interface UserSummary {
  id: string;
  username: string;
  display_name: string | null;
  system_role: string;
}

/** `POST /api/v1/auth/login` 响应：同时下发刷新令牌 Cookie */
export interface LoginResponse {
  request_id: string;
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserSummary;
}

/** `POST /api/v1/auth/refresh` 响应：只给令牌，不含账号（账号另调 `/me`） */
export interface RefreshResponse {
  request_id: string;
  access_token: string;
  token_type: string;
  expires_in: number;
}

/** `GET /api/v1/auth/me` 响应 */
export interface MeResponse {
  request_id: string;
  user: UserSummary;
}
