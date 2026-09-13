import { CheckCircle2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { HealthComponent, HealthResponse } from "@/types/api";

const COMPONENT_LABELS: Record<string, string> = {
  mysql: "MySQL",
  redis: "Redis",
  milvus: "Milvus",
};

const PREFERRED_ORDER = ["mysql", "redis", "milvus"];

function labelFor(key: string): string {
  return COMPONENT_LABELS[key] ?? key;
}

/** 已知组件按固定顺序展示，未知组件追加在后（后端新增依赖时不至于漏显示） */
function orderComponentKeys(
  components: Record<string, HealthComponent>,
): string[] {
  const keys = Object.keys(components);
  return [
    ...PREFERRED_ORDER.filter((key) => keys.includes(key)),
    ...keys.filter((key) => !PREFERRED_ORDER.includes(key)),
  ];
}

export function SystemStatusContent({ health }: { health: HealthResponse }) {
  const keys = orderComponentKeys(health.components);
  const downCount = keys.filter(
    (key) => health.components[key].status !== "ok",
  ).length;
  const overallOk = health.status === "ok";

  return (
    <Card data-testid="system-status-content" className="border-slate-200 shadow-sm">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="text-lg">后端依赖状态</CardTitle>
            <CardDescription>
              {overallOk
                ? "全部依赖可用"
                : `${downCount} / ${keys.length} 个依赖不可用`}
            </CardDescription>
          </div>
          <Badge
            data-testid="overall-status"
            className={cn(
              "border-transparent",
              overallOk
                ? "bg-emerald-50 text-emerald-700"
                : "bg-amber-50 text-amber-700",
            )}
          >
            {health.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <ul className="divide-y divide-slate-100">
          {keys.map((key) => {
            const component = health.components[key];
            const ok = component.status === "ok";
            return (
              <li
                key={key}
                className="flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900">
                    {labelFor(key)}
                  </p>
                  {ok ? null : (
                    <p className="mt-1 break-words text-xs text-red-700">
                      {component.error ?? "不可用"}
                    </p>
                  )}
                </div>
                <span
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1 text-xs font-medium",
                    ok ? "text-emerald-700" : "text-red-700",
                  )}
                >
                  {ok ? (
                    <CheckCircle2 className="size-4" aria-hidden="true" />
                  ) : (
                    <XCircle className="size-4" aria-hidden="true" />
                  )}
                  {ok ? "可用" : "不可用"}
                </span>
              </li>
            );
          })}
        </ul>
        <p className="mt-4 text-xs text-slate-400">
          request_id：{health.request_id}
        </p>
      </CardContent>
    </Card>
  );
}
