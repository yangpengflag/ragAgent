## 0. 环境准备（一次性基建）

- [ ] 0.1 复制 `.env.example` 为仓库根 `.env`，按本机填写（`MYSQL_PASSWORD`、`APP_SECRET_KEY` 等），并确认 `.env` 已被 `.gitignore` 忽略
- [ ] 0.2 创建 MySQL 库 `ragagent`（开发）与 `ragagent_test`（测试），不存在则创建
- [ ] 0.3 幂等创建 Milvus database `ragagent`，验证 `list_databases()` 中包含 `ragagent`
- [ ] 0.4 确认三个中间件可用：`mysql8` 服务 Running、Redis 容器 6379、Milvus standalone healthy（异常时用 `docker compose up -d --force-recreate standalone` 修复）
- [ ] 0.5 验证 uv 环境落在 D 盘：`uv cache dir` 输出以 `D:` 开头，且安装前后记录 C 盘剩余空间

## 1. 工程初始化与测试基建

- [ ] 1.1 创建 `backend/` 目录：`app/{api/v1,core,models,integrations}`、`tests/`、`alembic/`，每个包带 `__init__.py`（其余包目录由各自 change 创建）
- [ ] 1.2 编写 `pyproject.toml`：依赖含 **httpx**（`TestClient` 硬依赖）；设置 `[tool.uv] package = false`；配置 ruff 规则集 `E,F,I,UP,B,SIM` 与 mypy overrides（`pymysql/pymilvus/alembic` 忽略缺 stub；`app.domain.*` 开 strict）
- [ ] 1.3 用 `uv` 创建虚拟环境并生成 `uv.lock`；验证 `.venv/pyvenv.cfg` 的 `home` 指向 `D:\Programs\uv-python`
- [ ] 1.4 配置 `pytest`（asyncio 模式、测试路径）与 `tests/conftest.py` 骨架
- [ ] 1.5 红灯：写测试——`create_app()` 返回 FastAPI 实例，`/openapi.json` 可访问，未知路径返回统一 404 错误信封
- [ ] 1.6 绿灯：实现最小 `create_app()`（无路由、中间件与异常处理器挂载点留空）
- [ ] 1.7 红灯：写测试——conftest 提供配置隔离 fixture（`Settings(_env_file=None)` + `monkeypatch.delenv`），断言测试不会读到仓库根 `.env`
- [ ] 1.8 绿灯：实现 conftest 通用 fixture（配置隔离、临时库命名）
- [ ] 1.9 编写 `backend/README.md` 骨架（目录说明与命令占位，内容在 7.8 补全）

> **约束**：§3 与 §4 的所有红灯统一使用 `TestClient(create_app())`，不得自建临时 app，避免两套装配并存。

## 2. 配置层

- [ ] 2.1 红灯：写测试——缺少 `MYSQL_HOST` 时构造 Settings 抛出异常，且错误信息与日志中均包含 `MYSQL_HOST` 字样
- [ ] 2.2 绿灯：实现 `core/config.py` 的 Settings（Pydantic BaseSettings，`lru_cache` 缓存）
- [ ] 2.3 红灯：写测试——通过 `create_app()` 启动且缺少 `MYSQL_HOST` 时启动失败，不会进入可服务状态
- [ ] 2.4 绿灯：`create_app()` 首行实例化 Settings
- [ ] 2.5 红灯：写测试——数值型配置被正确转换；可选配置缺失时使用默认值；密码类配置为空串时被归一化为未设置
- [ ] 2.6 绿灯：补全默认值、类型转换与空串归一化逻辑
- [ ] 2.7 重构：`.env` 路径以 `Path(__file__).resolve().parents[2]` 定位仓库根；配置分组为 app / mysql / redis / milvus / logging / health；同步 `.env.example`

## 3. 结构化日志与 request_id

- [ ] 3.1 红灯：写测试——日志输出为可解析 JSON，包含时间戳、级别、消息字段
- [ ] 3.2 绿灯：实现 `core/logging.py`（structlog JSON renderer）
- [ ] 3.3 红灯：写测试——未携带 `X-Request-ID` 时响应头与响应体均含非空 `request_id`；携带时沿用；请求头名大小写不敏感
- [ ] 3.4 绿灯：实现 `request_id` 中间件（生成/沿用 + contextvar 绑定 + 响应头与响应体双写）
- [ ] 3.5 红灯：写测试——该请求产生的日志条目自动携带同一个 `request_id`
- [ ] 3.6 绿灯：日志处理器集成 contextvar 注入
- [ ] 3.7 红灯：写测试——日志中出现 token/password/secret/api_key 类字段时其值被脱敏
- [ ] 3.8 绿灯：实现敏感字段过滤
- [ ] 3.9 重构：收敛日志与中间件配置到 `core/`，路由层无日志样板代码

## 4. 统一错误信封

- [ ] 4.1 红灯：写测试——测试路由抛出资源不存在异常时返回 404，`error_code` 为 `not_found`，响应含 `request_id`
- [ ] 4.2 绿灯：定义 `AppError` 与 `NotFoundError`，注册 `AppError` 处理器，并挂一条测试路由
- [ ] 4.3 红灯：写测试——参数校验失败返回 422、`error_code` 为 `validation_error`、`details` 含字段级信息
- [ ] 4.4 绿灯：注册 `RequestValidationError` 处理器
- [ ] 4.5 红灯：写测试——未预期异常返回 500、`error_code` 为 `internal_error`、响应不含堆栈
- [ ] 4.6 绿灯：注册通用 `Exception` 处理器，堆栈只写日志
- [ ] 4.7 重构：只抽取实际用到的三个错误码常量，移除测试路由或收敛到测试专用 app

## 5. 数据库骨架与迁移

- [ ] 5.1 红灯：写测试——在 SQLite 内存库上 `create_all` 建测试模型：插入后主键/创建时间/更新时间自动填充且软删标记为空；更新后创建时间不变、更新时间变晚；执行 `soft_delete()` 后行仍在且 `deleted_at` 非空
- [ ] 5.2 绿灯：实现 `models/base.py`——公共 mixin（UUID v7 主键 default、BINARY(16) TypeDecorator 带 SQLite 回退、`created_at` 无 `onupdate`、`updated_at`、`deleted_at`、`soft_delete()`）
- [ ] 5.3 红灯：写测试——`get_db` 在正常与异常路径下均关闭会话
- [ ] 5.4 绿灯：实现 `core/db.py`——engine（QueuePool + 预检）、sessionmaker、`get_db` 依赖
- [ ] 5.5 初始化 Alembic，`env.py` 读取统一配置中的数据库 URL
- [ ] 5.6 准备迁移测试环境：`ragagent_test` 库执行 `drop/create database`
- [ ] 5.7 红灯：写测试——连续两次 upgrade 为幂等操作；`downgrade base` 后 `alembic_version` 清空；`heads` 唯一
- [ ] 5.8 绿灯：生成首个迁移（空迁移，仅建立版本基线；`downgrade()` 为空实现，作为规约唯一例外记录在 `design.md`）
- [ ] 5.9 重构：时间统一由应用层以 `datetime.now(timezone.utc)` 生成，禁止 `func.now()` / `CURRENT_TIMESTAMP` / `datetime.now()`

## 6. 健康检查端点

- [ ] 6.0 红灯：写测试——定义探针接口（返回组件状态），并断言健康检查编排层只依赖该接口、不直接构造客户端
- [ ] 6.1 绿灯：实现探针接口与编排层
- [ ] 6.2 红灯：写测试——注入三态探针：全部可用 → 200 且 `status` 为 `ok`；Milvus 不可用 → 仍 200、`status` 为 `degraded`、Milvus `status` 为 `down` 且 `error` 有原因；探针超时 → 该组件标 `down` 且附带超时原因
- [ ] 6.3 绿灯：实现 `GET /api/v1/health` 与响应模型（`response_model` + `summary` + `tags`，契约见 `design.md` D8）
- [ ] 6.4 红灯：写测试——真实探针（MySQL `SELECT 1` / Redis `PING` / Milvus 连接 `ragagent`）在目标不可达时于超时内返回 `down`
- [ ] 6.5 绿灯：实现三个真实探针并落到 `integrations/`，各自显式设置超时
- [ ] 6.6 重构：编排层收敛为薄函数，探针实现与编排分离

## 7. 应用装配与集成验证

- [ ] 7.1 补齐 `create_app()`：lifespan 资源管理、中间件、异常处理器、路由注册、CORS
- [ ] 7.2 实现 `main.py` 入口，端口取自 `Settings.APP_PORT`（默认 8000），不硬编码
- [ ] 7.3 红灯：写测试——启动应用后调用 `/api/v1/health` 返回 200（端到端冒烟）
- [ ] 7.4 绿灯：修复装配问题直至冒烟通过
- [ ] 7.5 真机验证：启动服务，`curl /api/v1/health` 返回 200 且 `components` 中 mysql / redis / milvus 均为 `ok`
- [ ] 7.6 真机验证：停掉 Redis 容器后健康检查在超时内返回 200，且 `components.redis.status` 为 `down`
- [ ] 7.7 全量门禁：`uv run pytest` 全绿、`uv run ruff check` 与 `uv run mypy` 零错误
- [ ] 7.8 补全 `backend/README.md`，更新 `AGENTS.md` 的启动/测试命令，提交变更
