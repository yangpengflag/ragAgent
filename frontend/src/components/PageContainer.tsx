import type { ReactNode } from "react";

interface PageContainerProps {
  title: string;
  description?: string;
  /** 页面标题右侧操作区 */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * 页面统一容器：微渐变背景 + 响应式侧边距 + 标题层级。
 * 遵循 `styling-conventions.md` 的"页面结构骨架"。
 */
export function PageContainer({
  title,
  description,
  actions,
  children,
}: PageContainerProps) {
  return (
    <div className="min-h-full bg-gradient-to-b from-slate-50 to-white">
      <div className="mx-auto max-w-5xl px-8 py-16 sm:px-12 lg:px-16">
        <div className="mb-10 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-slate-900 lg:text-4xl">
              {title}
            </h1>
            {description ? (
              <p className="mt-3 text-base text-slate-500">{description}</p>
            ) : null}
          </div>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </div>
        <div className="space-y-8">{children}</div>
      </div>
    </div>
  );
}
