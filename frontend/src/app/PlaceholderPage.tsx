import { Construction } from "lucide-react";

import { PageContainer } from "@/components/PageContainer";
import { Card, CardContent } from "@/components/ui/card";

interface PlaceholderPageProps {
  title: string;
  description?: string;
}

/**
 * 占位页：导航项已接线但页面由后续 change 实现。
 * 用统一的空态呈现，避免出现白屏。
 */
export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <PageContainer title={title} description={description}>
      <Card className="border-slate-200 shadow-sm">
        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
          <span className="flex size-12 items-center justify-center rounded-full bg-slate-100">
            <Construction className="size-6 text-slate-500" aria-hidden="true" />
          </span>
          <p className="text-sm font-medium text-slate-900">功能建设中</p>
          <p className="max-w-sm text-sm text-slate-500">
            本页面将在后续变更中交付。当前版本已包含导航、布局与统一的请求层。
          </p>
        </CardContent>
      </Card>
    </PageContainer>
  );
}
