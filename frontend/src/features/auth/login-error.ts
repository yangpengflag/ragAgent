import { ApiError } from "@/lib/api/errors";

/**
 * 登录失败 → 可读文案。
 *
 * 两条硬要求：
 * - **不区分账号是否存在**：凭据错误统一文案，避免账号枚举
 * - **不依赖响应体**：后端 500 可能缺 CORS 头导致响应体读不到
 *   （`notes/scaffold/residual-risks.md` 第 3 条），此时 `ApiError` 仍有
 *   由状态码兜底出来的 `error_code` 与通用 message，这里必须有默认值
 */
export function toLoginMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.error_code === "rate_limited") {
      return "尝试过于频繁，请稍后再试";
    }
    if (error.error_code === "unauthorized") {
      return "用户名或密码错误";
    }
    return error.message || "登录失败，请稍后重试";
  }
  return "登录失败，请稍后重试";
}
