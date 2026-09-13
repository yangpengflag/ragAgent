import { apiFetch } from "@/lib/api/client";
import type { HealthResponse } from "@/types/api";

/** 读取后端健康检查结果（后端不可用时抛 ApiError） */
export function fetchHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/api/v1/health");
}
