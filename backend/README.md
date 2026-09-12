# RAG Agent 后端

企业知识库与智能问答系统（EKB）的后端服务，Python 3.12 + FastAPI。

## 环境要求

- Python 3.12（由 `uv` 管理，安装目录 `D:\Programs\uv-python`）
- MySQL 8（库 `ragagent` / `ragagent_test`）
- Redis 6379
- Milvus 19530（database `ragagent`）

## 常用命令

```bash
# 安装依赖（含 dev 组）
uv sync

# 运行测试
uv run pytest

# 静态检查
uv run ruff check .
uv run mypy app

# 启动服务（模块级 app 与启动入口由任务 7.2 提供，当前不可用）
uv run uvicorn app.main:app --reload
```

## 环境验证记录

| 日期 | 项 | 结果 |
|---|---|---|
| 2026-09-12 | MySQL 库 `ragagent` / `ragagent_test` | 已创建（utf8mb4） |
| 2026-09-12 | Milvus database `ragagent` | 已幂等创建 |
| 2026-09-12 | 中间件可用性 | MySQL Running / Redis Up / Milvus healthy |
| 2026-09-12 | uv 环境位置 | cache `D:\uv-cache`、解释器 `D:\Programs\uv-python`（venv 在 `backend/.venv`） |

## 目录结构

```
app/
├── api/v1/         路由（薄层：校验 → 鉴权 → 调 service）
├── core/           配置、日志、安全、依赖注入、异常
├── domain/         纯领域层（零 I/O、零框架依赖）
├── integrations/   外部依赖适配（mineru / dashscope / milvus / redis / storage）
├── models/         SQLAlchemy 模型
├── schemas/        Pydantic Schema
└── services/       业务编排
tests/              测试（镜像 app/ 结构）
alembic/            数据库迁移
```

详细约定见仓库根 `AGENTS.md` 与 `.codebuddy/rules/backend-conventions.md`。
