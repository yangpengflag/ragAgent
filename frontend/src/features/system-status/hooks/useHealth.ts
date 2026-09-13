import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "@/features/system-status/api";

/**
 * 系统健康状态查询。
 *
 * 健康检查是"依赖是否可用"的实时视图，不做轮询（避免无谓请求），
 * 由用户手动刷新或重试触发。
 *
 * `retry: 0`：失败时立刻呈现错误态与重试按钮，而不是等待自动重试；
 * 后端不可用时自动重试只会放大请求量，且把错误反馈拖后。
 */
export function useHealth() {
  return useQuery({
    queryKey: ["system-status", "health"],
    queryFn: fetchHealth,
    retry: 0,
    refetchOnWindowFocus: false,
  });
}
