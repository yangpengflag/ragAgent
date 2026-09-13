import { Inbox, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

/** 空态：请求成功但没有组件数据（后端版本不匹配等） */
export function SystemStatusEmpty({ onRetry }: { onRetry: () => void }) {
  return (
    <Card data-testid="system-status-empty" className="border-slate-200 shadow-sm">
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-slate-100">
          <Inbox className="size-6 text-slate-500" aria-hidden="true" />
        </span>
        <p className="text-sm font-medium text-slate-900">暂无组件状态数据</p>
        <p className="max-w-sm text-sm text-slate-500">
          后端返回的健康检查结果中没有组件信息，可能是后端版本不匹配。可重试一次或联系管理员。
        </p>
        <Button variant="outline" onClick={onRetry}>
          <RefreshCw className="size-4" />
          重试
        </Button>
      </CardContent>
    </Card>
  );
}
