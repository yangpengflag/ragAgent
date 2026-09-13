# RAG Agent 后端

企业知识库与智能问答系统（EKB）的后端服务，Python 3.12 + FastAPI。

## 环境要求

- Python 3.12（由 `uv` 管理，安装目录 `D:\Programs\uv-python`）
- MySQL 8：库 `ragagent`（开发）/ `ragagent_test`（测试）
- Redis 6379
- Milvus 19530，database `ragagent`

配置来自仓库根 `.env`（由 `.env.example` 复制）。

## 常用命令

```bash
# 安装依赖（含 dev 组）
uv sync

# 运行测试（MySQL 不可用时迁移测试自动跳过）
uv run pytest

# 静态检查
uv run ruff check .
uv run mypy app

# 启动服务（端口取自 Settings.APP_PORT，默认 8000）
uv run python -m app.main
# 或开发模式（自动重载）
uv run uvicorn --factory app.main:create_app --reload

# 数据库迁移
uv run alembic upgrade head
uv run alembic revision -m "描述"          # 新增迁移
uv run alembic downgrade -1                # 回退一步
ALEMBIC_TARGET=test uv run alembic upgrade head   # 作用于测试库
```

## 目录结构

```
app/
├── api/v1/         路由（薄层：校验 → 依赖注入 → 调 service）
├── core/           配置、日志、request_id、数据库、异常与错误处理器
├── domain/         纯领域层（零 I/O、零框架依赖）
├── integrations/   外部依赖适配（健康探针；后续 mineru / dashscope / milvus / storage）
├── models/         SQLAlchemy 模型（Base + 公共字段）
└── schemas/        Pydantic Schema
tests/              测试（当前平铺；首个业务模块起按 tests/<层>/ 组织）
alembic/            数据库迁移（env.py 从应用配置取 URL）
```

> `services/`、`tasks/` 由后续 change 创建。

## 关键约定

- **配置**：单一 `Settings`，`.env` 定位到仓库根；缺必填项时启动即失败（含变量名，并记日志）
- **请求追踪**：`X-Request-ID` 入站沿用 / 缺失生成，出站写响应头与信封 `request_id`
- **日志**：structlog JSON，敏感字段（password / token / secret / api_key 等）**递归**脱敏
- **错误信封**：`{ request_id, error_code, message, details? }`；500 不含堆栈，堆栈只进日志
- **主键**：UUID v7，MySQL 存 `BINARY(16)`，SQLite 回退 `CHAR(32)`（便于内存库测试）
- **时间**：应用层生成 naive UTC（禁止 `func.now()` / `CURRENT_TIMESTAMP`）

## 健康检查

`GET /api/v1/health` 报告 MySQL / Redis / Milvus 连通性：

```json
{
  "request_id": "...",
  "status": "ok",
  "components": {
    "mysql": { "status": "ok", "error": null },
    "redis": { "status": "ok", "error": null },
    "milvus": { "status": "ok", "error": null }
  }
}
```

任一依赖不可用时仍返回 **200**，`status` 变为 `degraded` 并在对应组件给出原因——
健康检查用于排障而非熔断。各探针均有显式超时，不会挂起：
Redis 显式关闭重试（默认重试会把 2s 超时放大到 26s），Milvus 在受限线程中执行（SDK 连接重试无可靠上限）。

## 环境验证记录

| 日期 | 项 | 结果 |
|---|---|---|
| 2026-09-12 | MySQL 库 `ragagent` / `ragagent_test` | 已创建（utf8mb4） |
| 2026-09-12 | Milvus database `ragagent` | 已幂等创建 |
| 2026-09-12 | uv 环境位置 | cache `D:\uv-cache`、解释器 `D:\Programs\uv-python`（venv 在 `backend/.venv`） |
| 2026-09-12 | `/api/v1/health` 真机 | 200，三组件均 `ok`，`request_id` 头体一致 |
| 2026-09-12 | 停 Redis 后 `/api/v1/health` | 200，`degraded`，redis `down`（超时原因），MySQL/Milvus 正常 |

详细约定见仓库根 `AGENTS.md` 与 `.codebuddy/rules/backend-conventions.md`。
