// @vitest-environment node
// 该用例只读 package.json，不需要 DOM；node 环境下 import.meta.url 才是 file URL。
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

interface PackageJson {
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
}

const pkg = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf8"),
) as PackageJson;

/** 样式规约明确禁止引入的 UI 组件库与 CSS-in-JS 方案 */
const FORBIDDEN_UI_LIBS = [
  "@mui/material",
  "@mui/base",
  "@chakra-ui/react",
  "antd",
  "@mantine/core",
  "styled-components",
  "@emotion/react",
  "@emotion/styled",
  "@vanilla-extract/css",
];

describe("依赖门禁", () => {
  it("未引入样式规约禁止的 UI 库", () => {
    const allDependencies = { ...pkg.dependencies, ...pkg.devDependencies };

    for (const lib of FORBIDDEN_UI_LIBS) {
      expect(allDependencies).not.toHaveProperty(lib);
    }
  });

  it("样式栈为 Tailwind CSS 4 + shadcn/ui 依赖组合", () => {
    const allDependencies = { ...pkg.dependencies, ...pkg.devDependencies };

    expect(allDependencies).toHaveProperty("tailwindcss");
    expect(allDependencies).toHaveProperty("tailwind-merge");
    expect(allDependencies).toHaveProperty("class-variance-authority");
  });

  it("图标统一来源为 lucide-react", () => {
    expect(pkg.dependencies).toHaveProperty("lucide-react");
  });
});
