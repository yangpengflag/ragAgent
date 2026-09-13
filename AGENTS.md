# 项目说明

> 本项目为**企业知识库与智能问答系统（EKB）**，采用 Python FastAPI + React Vite 前后端分离架构，以 MinerU 解析 + DashScope 向量/生成 + Milvus 检索构建 RAG 能力。
>
> 权威规格见 [`openspec/project.md`](openspec/project.md)。本文件说明**协作方式**：多 IDE 适配、硬规则、目录入口、仓结构。

## 多 IDE 适配说明（Qoder / CodeBuddy / Claude / ZCode）

本项目同时适配 **Qoder**、**CodeBuddy**、**Claude**（Claude Code）与 **ZCode** 四款 AI IDE。四者的 Harness 配置与 OpenSpec 产物**内容完全镜像**，仅目录名不同：

| 用途 | Qoder 路径 | CodeBuddy 路径 | Claude 路径 | ZCode 路径 |
| --- | --- | --- | --- | --- |
| 规则 / 命令 / skills / agents | `.qoder/` | `.codebuddy/` | `.claude/` | `.zcode/` |
| OpenSpec 产物（真相来源） | `openspec/`（四者共用，无差异） | 同左 | 同左 | 同左 |

> 约定：四款 IDE 的 Harness 配置内容一致；改一处须同步其余三处。后续小节若出现 `<harness>/` 占位符，按你的 IDE 替换为 `.qoder/`、`.codebuddy/`、`.claude/` 或 `.zcode/`。

## 硬规则（不可违反）

1. **任何代码改动前必须先走 OpenSpec 流程**：在 `openspec/changes/<change-name>/` 下产出 `proposal.md` → `design.md` → `tasks.md`，人类签字后才动代码。
2. **单仓结构**：`backend/` 与 `frontend/` 是同一 git 仓库下的普通目录（**不是** submodule）。所有 git 操作在仓库根目录执行。
3. **TDD 不可绕过**：实现阶段严格 RED → GREEN → REFACTOR，先写失败测试。
4. **YAGNI / DRY**：不做没要求的事，不搞预防性抽象。
5. **变更完成后归档**：把 `openspec/changes/<name>/` 移入 `openspec/changes/archive/<date>-<name>/`。
6. **密钥不入仓**：所有凭据走环境变量，`.env` 在 `.gitignore` 中，仅提交 `.env.example`。

## 快速入口

| 资源 | 路径（`<harness>/` 按你的 IDE 替换） |
| --- | --- |
| 编码规约 | `<harness>/rules/coding-conventions.md` |
| 工作流规则 | `<harness>/rules/spec-driven-workflow.md` |
| 后端编码规约 | `<harness>/rules/backend-conventions.md` |
| 前端编码规约 | `<harness>/rules/frontend-conventions.md` |
| 数据库规约 | `<harness>/rules/database-conventions.md` |
| API 规约 | `<harness>/rules/api-conventions.md` |
| 样式规约 | `<harness>/rules/styling-conventions.md` |
| OpenSpec 命令 | `<harness>/commands/opsx/{propose,apply,archive,explore}.md` |
| OpenSpec skills | `<harness>/skills/openspec-{propose,apply-change,archive-change,explore}/SKILL.md` |
| Superpowers skills | `<harness>/skills/{brainstorming,writing-plans,executing-plans,test-driven-development,subagent-driven-development,using-git-worktrees,requesting-code-review,verification-before-completion}/SKILL.md` |
| 自定义 subagents | `<harness>/agents/*.md` |
| OpenSpec 配置 | [`openspec/config.yaml`](openspec/config.yaml) |
| 项目级 spec | [`openspec/project.md`](openspec/project.md) |
| 环境样例 | [`.env.example`](.env.example) |

## 仓结构

```
ekb/                          ← 单一 git 仓库
├─ openspec/                  # 四 IDE 共用的规格真相来源
│   ├─ project.md
│   ├─ specs/<capability>/spec.md
│   ├─ changes/               # 进行中的变更
│   ├─ changes/archive/       # 已归档
│   ├─ notes/                 # 人类可读 brief（不进工作流）
│   └─ parked/                # 挂起的变更
├─ backend/                   # Python FastAPI
│   ├─ app/
│   │   ├─ api/v1/
│   │   ├─ domain/            # ★ 纯领域层，零 I/O
│   │   ├─ services/
│   │   ├─ integrations/      # mineru / dashscope / milvus / redis / storage
│   │   ├─ models/ schemas/ tasks/
│   ├─ tests/
│   ├─ alembic/
│   └─ pyproject.toml
├─ frontend/                  # React + Vite
│   ├─ src/
│   │   ├─ app/  components/  lib/  features/
│   └─ package.json
├─ docker/                    # 可选：本项目依赖的 compose 复本（便于复现）
├─ storage/                   # 原始文件 + 解析产物（gitignored）
├─ .env.example
└─ AGENTS.md
```

> **目录约定（MUST）**：后端代码一律放 `backend/`，前端代码一律放 `frontend/`；仓库根**不放任何源码**，只放 `openspec/`、各 IDE harness 目录、`.env.example`、`AGENTS.md`、`.python-version`、`.gitignore` 等协作与配置文件。

### `backend/` — Python 后端

- **技术栈**：Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic + Celery
- **环境管理**：`uv`（`uv venv` / `uv sync` / `uv run`）
- **分层**：`api/` → `services/` → `domain/`（纯函数）→ `integrations/`
- **测试**：`uv run pytest`
- **质量**：`uv run ruff check` + `uv run mypy`
- **编码规约**：`<harness>/rules/backend-conventions.md`

### `frontend/` — React 前端

- **技术栈**：React 18 + Vite + TypeScript + Tailwind CSS 4 + shadcn/ui + lucide-react
- **状态**：TanStack Query（服务端状态）+ Zustand（本地 UI 状态）
- **测试**：Vitest + React Testing Library + jsdom，HTTP 由 **msw** 拦截（**不依赖真实后端**）
- **质量**：`npm run lint` + `npm run typecheck` + `npm run build`
- **目录**：`src/{app,components/ui,components,features,lib,store,types}`；测试文件与被测源码同目录（`Xxx.test.tsx`），共享测试基建在 `tests/`
- **请求层**：所有请求经 `src/lib/api/client.ts`（基址、Bearer 注入、401 刷新重放、错误归一化为 `ApiError`），字段名与后端一致不做转换
- **配置**：`frontend/.env` 的 `VITE_API_BASE_URL`（默认 `http://localhost:8000`；CORS 已放行 `http://localhost:5173`）
- **编码规约**：`<harness>/rules/frontend-conventions.md`

## 本地开发

本机中间件现状（详见 `openspec/project.md`）：MySQL 3306 ✅、Redis 6379 ✅（容器）、Milvus 19530 ✅（`D:\docker-milvus` compose）。

```bash
# 后端
cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.main                     # 端口取自 APP_PORT（默认 8000）
uv run uvicorn --factory app.main:create_app --reload   # 开发模式

# 前端
cd frontend
npm install
npm run dev          # 5173
npm run test         # Vitest（后端未启动也能全绿）
npm run lint && npm run typecheck && npm run build
```

若 Milvus 未起：

```bash
cd D:\docker-milvus
docker compose up -d
# 若 milvus-standalone 启动即退出，执行：
docker compose up -d --force-recreate standalone
```

## OpenSpec 工作流

```bash
/opsx:explore <想法>      # 探索、对齐
/opsx:propose <idea>      # 创建变更（proposal / design / tasks）
/opsx:apply               # 按 tasks.md 推进实现（走 TDD skill）
/opsx:archive             # 归档完成的变更
```

切换 IDE 后如遇斜杠命令未生效，重启当前 IDE 让命令加载即可，无需重复初始化。

## 质量底线

- 所有改动走 TDD。
- 主分支测试始终绿灯；`ruff` + `mypy` 零错误。
- 公开 API 改动必须先有对应 spec 更新。
- 检索相关优化必须有 golden QA 评测数据支撑。
