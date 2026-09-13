import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/plus-jakarta-sans/600.css";
import "@fontsource/plus-jakarta-sans/700.css";
import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router-dom";

import { AppProviders } from "@/app/providers";
import { routes } from "@/app/routes";

const router = createBrowserRouter(routes, {
  future: { v7_relativeSplatPath: true },
});

const container = document.getElementById("root");
if (container === null) {
  throw new Error("未找到 #root 挂载节点");
}

createRoot(container).render(
  <StrictMode>
    <AppProviders>
      <RouterProvider router={router} future={{ v7_startTransition: true }} />
    </AppProviders>
  </StrictMode>,
);
