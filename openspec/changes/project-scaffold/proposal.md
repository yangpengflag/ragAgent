## Why

仓库当前只有规格与协作文档（`openspec/`、`AGENTS.md`、`.codebuddy/`、`.env.example`），**没有任何可执行代码**。后续所有能力（文档解析、切分、向量化、检索、问答）都依赖一个统一的应用骨架：配置加载、日志与 `request_id`、数据库会话、错误信封、健康检查、测试与质量门禁。

若让每个能力各自搭一套，会出现多份配置读取方式、多种错误格式、不一致的日志字段，等到集成时再统一成本极高。因此需要先把骨架立住，作为后续所有 change 的地基。

## What Changes

**环境准备（一次性基建，非应用运行时行为）**

- 由 `.env.example` 复制出仓库根 `.env` 并按本机环境填写
- 创建 MySQL 库 `ekb`（开发）与 `ekb_test`（测试），若不存在则创建
- 幂等创建 Milvus database `ekb`（项目级隔离单元）

**后端工程**

- 新建 `backend/` Python 工程（`uv` 管理，Python 3.12，锁定于 `.python-version`）
- 实现配置层：Pydantic Settings 从环境变量读取，必需项缺失时在**应用启动阶段** fail-fast
- 实现应用骨架：FastAPI 应用工厂、中间件挂载、路由注册、CORS
- 实现横切关注点：
  - `request_id`：入站读取 `X-Request-ID`（缺失则生成），出站同时写入响应头与响应体，并绑定到日志上下文
  - 结构化日志（JSON，自动携带 `request_id`，过滤敏感字段）
  - 全局异常处理器，统一错误信封 `{ request_id, error_code, message, details? }`
- 实现数据访问骨架：
  - SQLAlchemy 2.0 引擎与 `get_db` 依赖（请求结束必释放）
  - 公共 mixin：UUID v7 主键（存 `BINARY(16)`）、`created_at`（不可更新）、`updated_at`、`deleted_at` 与 `soft_delete()` 方法
  - Alembic 初始化与首个迁移（建 `alembic_version` 元数据，为后续 change 提供可回滚基线）
- 实现健康检查端点 `GET /api/v1/health`：报告应用状态，并分别探测 MySQL / Redis / Milvus 连通性（任一不可用仍返回 200，以 `components` 字段标注）
- 建立测试与质量门禁：pytest（含 `httpx` 与测试替身基建）、ruff、mypy
- 新增 `backend/README.md` 说明启动方式与常用命令

**不在本 change 范围内**：业务实体（KB / Document / Chunk / User）、鉴权、文档上传、MinerU 对接、向量 collection 建表、**全局软删查询过滤**（推迟到首个业务实体引入时）、UUID 与 BINARY(16) 互转工具、Celery worker 进程、CI 流水线、性能调优与连接池压测、前端骨架。

## Capabilities

### New Capabilities

- `project-scaffold`：应用骨架与横切基础设施——环境准备、配置加载、日志与 `request_id`、错误信封、数据库会话与迁移、健康检查、测试与质量门禁。

### Modified Capabilities

（无。本 change 不改动既有能力，仓库此前无 `specs/`。）

## Impact

- **新增目录/文件**：`backend/`（`app/`、`tests/`、`alembic/`、`pyproject.toml`、`uv.lock`、`README.md`）
- **依赖引入**：`fastapi`、`uvicorn`、`httpx`（测试）、`pydantic-settings`、`sqlalchemy`、`alembic`、`pymysql`、`redis`、`pymilvus`、`structlog`、`pytest`、`pytest-asyncio`、`ruff`、`mypy`
- **外部系统**：
  - MySQL：创建 `ekb` / `ekb_test` 两个库（一次性准备）
  - Milvus：幂等创建 database `ekb`（一次性准备，本 change 唯一的一次性写操作）
  - 运行时只读探测 MySQL / Redis / Milvus，不建业务表
- **配置**：依赖仓库根 `.env`（由 `.env.example` 复制）；新增变量需同步 `.env.example`
- **后续影响**：所有后续 change 的路由、service、Celery 任务均复用本骨架的配置、日志、错误处理与数据库会话
