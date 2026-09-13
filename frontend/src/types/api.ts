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
