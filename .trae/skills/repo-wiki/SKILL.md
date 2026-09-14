---
name: repo-wiki
description: 生成、增量维护并检索"仓库知识库"(Repo Wiki)。当用户想要自动梳理代码库结构、生成架构/模块文档、或基于全仓上下文问答时使用。对应 scripts/wiki-generator.ts。
---

# Repo Wiki 技能

让 AI 自动扫描 `backend/` 与 `frontend/` 子仓业务代码，生成结构化知识库到 `docs/wiki/`，支持问答与检索。

## 核心约定（MUST）

- **脚本只提取"结构骨架"**（包/类/接口/组件/路由/导出符号）。自然语言叙述（模块职责、调用关系）由你在**校验阶段**补充，不要指望脚本自动写散文。
- 产物是 **Markdown + Git 可追踪**，不引入向量库。检索靠 `INDEX.md` + 文件路径。

## 工作流程

### 1. 生成（全量）

```bash
npx tsx scripts/wiki-generator.ts
```

### 2. 增量更新（代码演进后）

```bash
npx tsx scripts/wiki-generator.ts --incremental
```

仅重生成源文件 mtime 变化的模块；`INDEX.md` 与 `architecture.md` 始终刷新。

### 3. 限定范围

```bash
npx tsx scripts/wiki-generator.ts --scope=backend
npx tsx scripts/wiki-generator.ts --scope=frontend
```

### 4. 检索（AI 问答时）

1. 先读 `docs/wiki/INDEX.md` 获取模块清单与链接。
2. 按用户问题定位到对应 `modules/<id>.md`，定向读取，必要时再回源文件确认。
3. 若 Wiki 过期（INDEX 时间戳早、或代码已变更），提示用户先跑增量更新。

## 校验清单（生成后 MUST 做）

- 打开 `INDEX.md`，确认模块覆盖完整（backend 各业务包 + frontend 各分组）。
- 对每个 `modules/*.md`，用一句话补"职责"段落（脚本留了占位）。
- 抽查 1–2 个模块的符号提取是否准确（误提取/漏提取）。
- 校验 `architecture.md` 的分层描述是否合理。

## 产物结构

```
docs/wiki/
  INDEX.md          # 总览 + 模块链接 + 时间戳
  architecture.md   # 分层架构 (ASCII)
  modules/<id>.md   # 单模块: 职责 / 关键文件 / 依赖
```

## 范围边界

- 仅扫描 `backend/` + `frontend/` 子仓业务代码（**已确认**）。
- **不**扫描 `openspec/`、`docs/`（本期不做，后续可扩展）。
- 脚本落父仓 `scripts/`，单仓结构下与代码同库管理（遵守项目硬规则 2）。

## 触发示例

- "帮我梳理一下整个项目的架构"
- "生成仓库 wiki"
- "代码改了，更新一下知识库"
- "todo 模块是做什么的？"（先读 INDEX 再定位 backend-todo / frontend-views）
