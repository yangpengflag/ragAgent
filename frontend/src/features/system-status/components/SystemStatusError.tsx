import { AlertCircle, RefreshCw } from "lucide-react";

import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { isApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

interface SystemStatusErrorProps {
  error: unknown;
  retrying: boolean;
  onRetry: () => void;
}

/** 错误态：给出可读原因与重试入口（后端未启动是最常见的形态） */
export function SystemStatusError({
  error,
  retrying,
  onRetry,
}: SystemStatusErrorProps) {
  const apiError = isApiError(error) ? error : null;

  return (
    <Card data-testid="system-status-error" className="border-slate-200 shadow-sm">
      <CardContent className="py-8">
        <Alert variant="destructive">
          <AlertCircle />
          <AlertTitle>无法获取系统状态</AlertTitle>
          <AlertDescription>
            <p data-testid="error-message">
              {apiError?.message ?? "发生未知错误，请稍后重试"}
            </p>
            {apiError ? (
              <p className="text-xs text-slate-500">
                错误码：{apiError.error_code}
                {apiError.request_id
                  ? ` · request_id：${apiError.request_id}`
                  : ""}
              </p>
            ) : null}
          </AlertDescription>
        </Alert>
        <Button className="mt-6" onClick={onRetry} disabled={retrying}>
          <RefreshCw className={cn("size-4", retrying && "animate-spin")} />
          {retrying ? "重试中…" : "重试"}
        </Button>
      </CardContent>
    </Card>
  );
}
