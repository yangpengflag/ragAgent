import { create } from "zustand";

/**
 * 本地 UI 状态（服务端状态一律走 TanStack Query，不入这里）。
 */
interface UiState {
  /** 移动端导航抽屉是否打开 */
  navOpen: boolean;
  setNavOpen: (open: boolean) => void;
}

export const useUiStore = create<UiState>((set) => ({
  navOpen: false,
  setNavOpen: (open) => set({ navOpen: open }),
}));
