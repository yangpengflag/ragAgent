import { LogOut, Menu } from "lucide-react";
import { useEffect } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { NAV_ITEMS, findNavItem } from "@/app/navigation";
import { Button } from "@/components/ui/button";
import { performLogout } from "@/features/auth/logout";
import { useSessionStore } from "@/features/auth/session-store";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/store/ui";

/**
 * 应用外壳：桌面固定侧边栏 + 内容区；小屏收起为抽屉。
 *
 * 不再注册"刷新失败"处理器：它已上移到路由最外层的 `AuthFailureBridge`——
 * 跳转登录恰恰发生在离开受保护路由时，挂在会被卸载的布局组件上是脆弱的。
 */
export function AppLayout() {
  const location = useLocation();
  const navOpen = useUiStore((state) => state.navOpen);
  const setNavOpen = useUiStore((state) => state.setNavOpen);
  const account = useSessionStore((state) => state.user);

  useEffect(() => {
    setNavOpen(false);
  }, [location.pathname, setNavOpen]);

  const current = findNavItem(location.pathname);

  return (
    <div className="flex min-h-screen bg-white">
      <aside
        data-testid="sidebar"
        className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white md:flex"
      >
        <BrandHeader />
        <nav aria-label="主导航" className="flex-1 space-y-1 p-3">
          <NavList />
        </nav>
        <p className="border-t border-slate-200 p-4 text-xs text-slate-500">
          企业知识库系统
        </p>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur md:px-6">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="md:hidden"
            aria-label="打开导航"
            onClick={() => setNavOpen(true)}
          >
            <Menu />
          </Button>
          <span className="text-sm font-semibold text-slate-900">
            {current?.label ?? "EKB"}
          </span>

          <div className="ml-auto flex items-center gap-3">
            {account !== null ? (
              <>
                <span
                  className="text-sm text-slate-600"
                  data-testid="current-account"
                >
                  {account.username}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => void performLogout()}
                >
                  <LogOut aria-hidden="true" />
                  登出
                </Button>
              </>
            ) : null}
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>

      <Sheet open={navOpen} onOpenChange={setNavOpen}>
        <SheetContent
          side="left"
          data-testid="sidebar-drawer"
          className="w-72 gap-0 p-0 md:hidden"
        >
          <SheetHeader className="border-b border-slate-200 px-4 py-3">
            <SheetTitle>EKB 企业知识库</SheetTitle>
            <SheetDescription>选择要进入的功能</SheetDescription>
          </SheetHeader>
          <nav aria-label="移动端导航" className="space-y-1 p-3">
            <NavList onNavigate={() => setNavOpen(false)} />
          </nav>
        </SheetContent>
      </Sheet>
    </div>
  );
}

function BrandHeader() {
  return (
    <div className="flex h-14 items-center gap-2 border-b border-slate-200 px-4">
      <span className="flex size-7 items-center justify-center rounded-md bg-blue-700 text-xs font-bold text-white">
        EK
      </span>
      <span className="text-sm font-semibold text-slate-900">企业知识库</span>
    </div>
  );
}

function NavList({ onNavigate }: { onNavigate?: () => void } = {}) {
  return (
    <>
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              isActive
                ? "bg-blue-50 text-blue-700"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
            )
          }
        >
          <item.icon className="size-4 shrink-0" aria-hidden="true" />
          <span>{item.label}</span>
        </NavLink>
      ))}
    </>
  );
}
