import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/** 加载态：骨架屏，避免进入页面时出现空白或布局跳动 */
export function SystemStatusSkeleton() {
  return (
    <Card
      data-testid="system-status-loading"
      aria-busy="true"
      className="border-slate-200 shadow-sm"
    >
      <CardHeader>
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-4 w-48" />
      </CardHeader>
      <CardContent className="space-y-5">
        {[0, 1, 2].map((index) => (
          <div key={index} className="flex items-center justify-between gap-4">
            <div className="space-y-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-3 w-40" />
            </div>
            <Skeleton className="h-4 w-16" />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
