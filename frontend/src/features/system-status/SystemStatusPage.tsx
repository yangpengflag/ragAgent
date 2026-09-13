import { RefreshCw } from "lucide-react";

import { PageContainer } from "@/components/PageContainer";
import { Button } from "@/components/ui/button";
import { SystemStatusContent } from "@/features/system-status/components/SystemStatusContent";
import { SystemStatusEmpty } from "@/features/system-status/components/SystemStatusEmpty";
import { SystemStatusError } from "@/features/system-status/components/SystemStatusError";
import { SystemStatusSkeleton } from "@/features/system-status/components/SystemStatusSkeleton";
import { useHealth } from "@/features/system-status/hooks/useHealth";
import { cn } from "@/lib/utils";

/**
 * 系统状态页：只做编排，展示细节在 `components/` 下的四个状态组件中。
 * 同时作为四态（Loading / Content / Empty / Error）的样板实现。
 *
 * 注：Empty 态是**前向兼容**分支——当前后端的健康接口恒定返回 mysql/redis/milvus
 * 三个组件，故真实链路下不会触发（单测用合成的空响应覆盖）。保留它是为了
 * 后端契约变化（例如未来按需返回组件、或返回体被网关裁剪）时不至于白屏。
 */
export function SystemStatusPage() {
  const { data, isPending, isError, error, isFetching, refetch } = useHealth();

  const handleRetry = () => {
    void refetch();
  };

  const hasComponents =
    data !== undefined && Object.keys(data.components).length > 0;

  return (
    <PageContainer
      title="系统状态"
      description="查看后端服务与依赖（MySQL / Redis / Milvus）的实时可用性。"
      actions={
        <Button
          variant="outline"
          onClick={handleRetry}
          disabled={isFetching || isPending}
        >
          <RefreshCw className={cn("size-4", isFetching && "animate-spin")} />
          刷新
        </Button>
      }
    >
      {isPending ? <SystemStatusSkeleton /> : null}

      {!isPending && isError ? (
        <SystemStatusError
          error={error}
          retrying={isFetching}
          onRetry={handleRetry}
        />
      ) : null}

      {!isPending && !isError && !hasComponents ? (
        <SystemStatusEmpty onRetry={handleRetry} />
      ) : null}

      {!isPending && !isError && hasComponents && data ? (
        <SystemStatusContent health={data} />
      ) : null}
    </PageContainer>
  );
}
