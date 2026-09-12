## Context

仓库当前只有规格与协作文档，无任何可执行代码。本机环境（2026-09-12 实测）：Python 3.12.12 已装于 `D:\Programs\uv-python`（uv 安装目录与缓存均已迁至 D 盘）；MySQL 8（3306）、Redis（6379，容器）、Milvus 2.5.10（19530，容器）均已可用；**C 盘仅剩约 2.6 GB**，虚拟环境与依赖缓存必须落在 D 盘。

**尚缺的环境前提**（若不先解决，实现到第 2、5、6 节会卡住）：

- 仓库根 `.env` 不存在（只有 `.env.example`）
- MySQL 库 `ragagent` / `ragagent_test` 未创建
- Milvus database `ragagent` 未创建

动机见 `proposal.md`，需求见 `specs/project-scaffold/spec.md`。本文件只写"怎么做"。

## Goals / Non-Goals

**Goals:**

- 建立所有后续 change 共用的后端骨架：环境准备、配置、日志、`request_id`、错误信封、数据库会话与迁移、健康检查
- 让"骨架是否正确"可被测试验证，而不是靠人肉点验；且测试不依赖本机中间件是否运行
- 锁定依赖与工具链，保证换机器可复现（`uv.lock` 入仓）
- 保证本地开发不污染 C 盘

**Non-Goals:**

- 不引入任何业务实体（KB / Document / Chunk / User）
- 不实现鉴权、文档上传、MinerU 对接、向量 collection 建表
- **不实现全局软删查询过滤**（骨架期无查询层，实现即 YAGNI）；只提供 `deleted_at` 字段与 `soft_delete()` 方法
- 不提供 UUID 与 BINARY(16) 互转工具（无消费者）
- 不引入 Celery worker 进程、CI 流水线
- 不做性能调优与连接池压测

## Decisions

### D1. 用 `uv` + `pyproject.toml` 管理环境与依赖，且标记为不可安装包

**选择**：`uv` 管理虚拟环境与依赖，依赖声明在 `backend/pyproject.toml`，`uv.lock` 入仓；`pyproject.toml` 中设置 `[tool.uv] package = false`，避免 `uv sync` 尝试构建安装项目本身（临时目录可能回落 C 盘）。

**备选**：① pip + requirements.txt —— 无锁文件，环境不可复现；② Poetry —— 解析慢，与既有 uv 工作流割裂；③ conda —— 本机虽有 miniconda，与 uv 混用易冲突。

**理由**：uv 已配置完成（安装目录与缓存都在 D 盘），解析快、锁文件可靠，与 `.python-version` 配合可固定解释器版本。

### D2. FastAPI 应用工厂 + lifespan，工厂在骨架最早期即提供

**选择**：`create_app()` 工厂返回 `FastAPI` 实例。**最小版本（空路由、挂载点留空）在工程初始化阶段就实现**，供后续所有需要 HTTP 周期的红灯使用；完整装配（lifespan / 中间件 / 异常处理器 / 路由 / CORS）在最后补齐。

**备选**：模块级 `app = FastAPI()` 单例 —— 测试时难以注入不同配置，且导入即产生副作用。

**理由**：测试需要独立实例；把最小工厂前置，可避免 `request_id` 与错误信封的红灯"无处挂载"。

### D3. 配置：单一 Settings 对象 + 启动期 fail-fast + 明确的环境隔离

**选择**：Pydantic `BaseSettings`，从环境变量与仓库根 `.env` 读取；`Settings` 以 `lru_cache` 缓存，并**在 `create_app()` 首行实例化**，使缺失必填项在启动阶段即失败。

配套约定：

- **`.env` 路径解析**：以 `Path(__file__).resolve().parents[2] / ".env"` 定位仓库根，避免 cwd 在 `backend/` 时静默读不到
- **空串归一化**：密码/令牌类配置（`MYSQL_PASSWORD`、`REDIS_PASSWORD`、`MILVUS_TOKEN`）空串一律归一化为"未设置"，避免 `redis.Redis(password="")` 触发 AUTH 空密码失败
- **必填项范围**：本 change 仅 `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_DATABASE` / `APP_SECRET_KEY` 为必填；DashScope 等留空不影响启动
- **测试隔离**：fixture 以 `Settings(_env_file=None)` 构造，配合 `monkeypatch.delenv`，确保不受仓库根 `.env` 影响

**备选**：分散在各模块 `os.getenv` —— 无法统一校验、无法在启动时暴露缺失项、类型靠手工转换。

### D4. `request_id`：头名 `X-Request-ID`，头体双写，contextvar 透传

**选择**：HTTP 中间件从 `X-Request-ID`（大小写不敏感）读取，缺失则生成；写入 contextvar 供日志使用；出站**同时**写入响应头 `X-Request-ID` 与响应体 `request_id` 字段。

**备选**：① 只放响应头 —— 排障时前端与日志聚合拿不到；② 不定义头名 —— 上下游无法对齐。

**理由**：contextvar 让日志在异步场景下仍能正确关联请求；头体双写兼顾链路追踪与调用方可读。

### D5. 日志：structlog 输出 JSON，带敏感字段过滤

**选择**：`structlog` 配置 JSON renderer，处理器链绑定 `request_id`；对 token / password / secret / api_key 类字段值做脱敏。

**备选**：标准库 `logging` + 自定义 Formatter —— 结构化能力弱，字段绑定麻烦。

**理由**：结构化日志便于检索排障；显式过滤满足"不记录敏感信息"的约束。

### D6. 错误信封：全局异常处理器 + 精简异常层次

**选择**：`AppError`（携带 `status_code` 与 `error_code`）+ 本 change 实际用到的 `NotFoundError`；注册三类处理器（`AppError`、`RequestValidationError`、`Exception`）。错误码常量只定义实际用到的三个（`not_found` / `validation_error` / `internal_error`），其余随业务 change 增量添加。

**备选**：每个路由 try/except 后返回 JSONResponse —— 重复代码且易漏；全量定义 10 个错误码常量 —— 骨架期零消费者。

### D7. 数据访问：UUID v7 + BINARY(16) + 应用层 UTC，软删只提供字段

**选择**：

- **主键**：UUID **v7**（时间有序），MySQL 侧以 `BINARY(16)` 存储。Python 3.12 标准库无 uuid7，在 `app/core/` 内自实现（约 20 行：48 位毫秒时间戳 + 版本号 + 随机/序列位），不引入额外依赖
- **`BINARY(16)` 实现**：自定义 `TypeDecorator`，`load_dialect_impl` 在 MySQL 上用 `BINARY(16)`、在 **SQLite 上回退为 `CHAR(32)`**，使测试可用 SQLite 内存库验证 mixin
- **时间**：`created_at` / `updated_at` 由应用层以 `datetime.now(timezone.utc)` 生成（naive UTC 写入），**禁止** `func.now()` / `CURRENT_TIMESTAMP` / `datetime.now()`（后者会落成 +08:00 本地时间）
- **软删**：只提供 `deleted_at` 字段与 `soft_delete()` 方法，**不注册全局查询过滤事件**
- **建表禁令范围**："`create_all` 禁用"针对应用 schema 变更路径；**测试内使用 SQLite 内存库 `create_all` 不在此禁令内**

**备选**：① 自增 BIGINT 主键 —— 暴露业务量、跨库合并易冲突；② uuid4 —— 随机写入造成索引页分裂；③ VARCHAR(36) —— 索引体积翻倍；④ 现在就加 `do_orm_execute` 全局软删过滤 —— 骨架期无查询层，属 YAGNI。

### D8. 健康检查：探针可注入，契约固定，连接 Milvus database `ragagent`

**选择**：定义探针接口（返回组件状态），编排层只依赖接口；`GET /api/v1/health` 响应契约固定为：

```json
{
  "request_id": "...",
  "status": "ok | degraded",
  "components": {
    "mysql": { "status": "ok | down", "error": null },
    "redis": { "status": "ok | down", "error": null },
    "milvus": { "status": "ok | down", "error": null }
  }
}
```

每项探测独立超时（默认 2s）。端点用 `response_model` + `summary` + `tags` 显式声明 OpenAPI。`ragagent` database 由环境准备阶段幂等创建，健康检查直接连接 `ragagent`。

**备选**：任一依赖不可用即返回 503 —— 容器编排会据此重启，本地开发误伤严重且掩盖故障定位信息；把探针硬编码进端点 —— 无法测试"不可用"与"挂起"两种场景。

**理由**：固定契约便于前端消费；可注入探针使三种状态都能在单元测试中覆盖，无需操作真实中间件。

### D9. 测试策略：测试替身基建先行，迁移测试用独立库

**选择**：

- **测试替身基建**（`conftest.py`）在建工程阶段就提供：配置隔离 fixture、探针三态 fixture（healthy / unhealthy / hang）
- **HTTP 测试**：统一使用 `TestClient(create_app())`，依赖 `httpx`（显式加入测试依赖）
- **数据库行为测试**：mixin 行为用 **SQLite 内存库 + `create_all`** 验证（见 D7），不落 MySQL
- **迁移测试**：使用独立 `ragagent_test` 库，前置 `drop/create database`、后置 `alembic downgrade base` 清理；**不使用事务回滚**——MySQL DDL 隐式提交，事务回滚对迁移无效
- 外部服务（DashScope / MinerU / Redis / Milvus）在单元测试中一律由替身替代

**备选**：直接连开发库跑测试 —— 污染数据且不可重复；迁移测试用事务回滚 —— 在 MySQL 上不成立。

### D10. 静态检查：ruff 指定规则集，mypy 用 overrides 处理缺 stub

**选择**：

- `ruff` 选用规则集 `E, F, I, UP, B, SIM`（**不用** `select = ["ALL"]`，避免噪音）
- `mypy` 全局非 strict，通过 `[[tool.mypy.overrides]]` 处理两类情况：
  - `module = ["pymysql.*", "pymilvus.*", "alembic.*"]` → `ignore_missing_imports = true`（这些包无 `py.typed`，默认严格度下会报缺 stub 而无法达到"零错误"）
  - `module = ["app.domain.*"]` → `strict = true`（领域层严格，把规矩立住；本 change `domain/` 基本为空，成本为零）

**备选**：全局 `--strict` —— 骨架阶段引入大量无关噪音；不做 overrides —— 7.x 的"mypy 零错误"无法达成。

## Risks / Trade-offs

- **`BINARY(16)` 在 SQLite 上的兼容性** → 自定义 TypeDecorator 通过 `load_dialect_impl` 回退为 `CHAR(32)`；若回退实现有坑，退路是 mixin 测试改用 MySQL `ragagent_test`（需先建测试模型表）。
- **UUID v7 自实现的正确性** → 只需保证"时间有序 + 全局唯一"两点，实现约 20 行并配单测（同毫秒内递增、跨毫秒递增、不重复）。
- **structlog 配置有一定学习成本** → 集中在单模块内配置，业务代码只用 `get_logger()`。
- **UUID 存 BINARY(16) 可读性差** → 当前不提供互转工具（无消费者）；首个业务实体 change 再补，届时一并处理日志 hex 输出。
- **空迁移与"downgrade 不得为空实现"规约冲突** → 首个迁移无表可建，作为**唯一例外**在此记录：`downgrade()` 为空实现是合理的（无对象可删）；迁移测试改为验证 Alembic 接线可用（`alembic_version` 版本推进/回退、`heads` 唯一），而非断言建表行为。
- **健康检查探测引入额外连接开销** → 探测超时 2s 且只做最小操作，开销可忽略。
- **Milvus 客户端初始化较慢** → 惰性初始化 + 显式超时；本 change 只探测连接，不建 collection。
- **Milvus 容器可能"孤儿化"**（`project.md` 已记已知坑）→ 真机验证前确认 `docker ps` 中 standalone 为 healthy；异常时用 `docker compose up -d --force-recreate standalone` 修复。
- **C 盘空间紧张** → `.venv` 建在 `backend/`（D 盘工作区），uv 缓存指向 `D:\uv-cache`；工程初始化时明确验收 `uv cache dir` 输出以 `D:` 开头。
- **mypy 非 strict 会放过部分类型问题** → 记录在案，随后续 change 逐步收紧。

## Migration Plan

1. **环境准备（一次性）**：复制 `.env` 并填写；创建 MySQL 库 `ragagent` 与 `ragagent_test`；幂等创建 Milvus database `ragagent`
2. 创建 `backend/` 工程与依赖声明，生成 `uv.lock`；建立最小 `create_app()` 与测试替身基建
3. 依次实现配置、日志与 `request_id`、错误信封、数据库骨架、健康检查，每步配套 RED→GREEN→REFACTOR
4. 生成首个 Alembic 迁移（空迁移，仅建立版本基线），验证 upgrade / downgrade / heads 唯一
5. 补齐完整应用装配，端到端冒烟
6. 真机验证：三组件可用；停掉 Redis 后健康检查在超时内返回并标注 `down`
7. 质量门禁：`pytest` 全绿、`ruff` 与 `mypy` 零错误
8. 更新 `AGENTS.md` 与 `backend/README.md` 的启动/测试命令，提交变更

**回滚**：本 change 不写入业务数据。如需撤销：删除 `backend/` 目录与 `uv.lock`；MySQL 侧 `DROP DATABASE ragagent_test`，`ragagent` 库执行 `alembic downgrade base` 后仅残留 `alembic_version` 空表；Milvus 侧保留 `ragagent` database（后续 change 仍需使用）。

## Open Questions

（无。原"是否引入 CI""mypy 何时 strict"两项已明确推迟，不影响本 change 的规格、方案与任务拆分。）
