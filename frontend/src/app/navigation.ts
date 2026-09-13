import type { LucideIcon } from "lucide-react";
import {
  Activity,
  FileText,
  Library,
  MessageSquare,
  Search,
} from "lucide-react";

export interface NavItem {
  /** 路由路径 */
  to: string;
  /** 导航文案 */
  label: string;
  icon: LucideIcon;
  /** 是否精确匹配（首页需要，否则任何路由都会命中） */
  end?: boolean;
}

/**
 * 导航配置。
 *
 * 本 change 只提供占位项，真实页面由后续 change 逐个替换
 * （knowledge-base / documents / chat / search）。
 */
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "系统状态", icon: Activity, end: true },
  { to: "/knowledge-bases", label: "知识库", icon: Library },
  { to: "/documents", label: "文档", icon: FileText },
  { to: "/chat", label: "问答", icon: MessageSquare },
  { to: "/search", label: "检索调试", icon: Search },
];

export function findNavItem(pathname: string): NavItem | undefined {
  return NAV_ITEMS.find((item) =>
    item.end ? pathname === item.to : pathname.startsWith(item.to),
  );
}
