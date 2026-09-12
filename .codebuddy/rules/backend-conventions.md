---
trigger: always_on
---
# 后端编码规约

后端采用 **Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic + Celery**。以下为 SHOULD 级约定（允许特例但需注释说明理由）。

## 分层架构

```
backend/app/
├── main.py                  ← FastAPI app 工厂、中间件挂载、路由注册
├── core/                    ← config / logging / security / deps / exceptions
├── api/v1/                  ← 路由（薄层）
├── domain/                  ★ 纯领域层：零 I/O、零框架依赖
│   ├── chunking/            结构树 / 打包 / 上下文注入 / overlap
│   ├── retrieval/           召回 / 融合 / 重排
│   └── generation/          prompt 组装 / 引用标注
├── services/                ← 编排层：事务、状态机、跨组件协调
├── integrations/            ← 外部依赖适配：mineru / dashscope / milvus / redis / storage
├── models/                  ← SQLAlchemy 模型
├── schemas/                 ← Pydantic v2 Schema
└── tasks/                   ← Celery 任务
```

依赖方向：`api → services → domain` + `services → integrations`。**反向依赖禁止**。

### `domain/` 铁律

- **禁止** import FastAPI / SQLAlchemy / redis / pymilvus / requests
- 只接收与返回纯数据结构（dataclass 或 Pydantic model）
- 切分器签名形如 `chunk(blocks: list[Block], cfg: ChunkConfig) -> list[Chunk]`
- 纯函数、确定性、单测毫秒级 —— 这是全仓 TDD 主战场

## 依赖注入

- 用 FastAPI `Depends()`，不用全局单例
- 数据库 Session：`Depends(get_db)`，请求结束即关
- 外部客户端（Milvus / Redis / DashScope）在 `core/deps.py` 中以 `lru_cache` 形式提供连接对象

## API 路由

- 只做：参数校验（Pydantic）+ 依赖鉴权 + 调 service + 返回 Schema
- 不写业务逻辑、不直接碰 ORM
- 路由函数全部 `async def`（除非调用阻塞 SDK，此时用 `run_in_threadpool`）
- 响应模型显式声明 `response_model=`，不用裸 dict

## Service

- 一个 service 类/模块负责一个业务域
- 事务边界在 service：以 `session.begin()` 显式控制
- 不把 ORM 模型直接返回给路由层，转 Pydantic Schema
- 业务异常抛 `core/exceptions.py` 中的自定义异常（携带 `error_code`），由全局 handler 转 HTTP

## Schema（Pydantic v2）

- 请求 Schema 命名 `XxxRequest`，响应 `XxxResponse`
- 字段 **snake_case**（见 `api-conventions.md`）
- 列表响应统一走分页信封
- 禁止在 Schema 里做 IO

## 外部集成（integrations/）

- 每个外部系统一个模块，暴露一个薄客户端类
- **超时必须显式设置**，禁止无限等待
- 失败策略显式化：fail-fast（鉴权/写库）或 fail-open（可选增强如重排）
- 第三方 SDK 的原始异常必须包装为内部异常，禁止泄漏 SDK 类型到上层

## 异步任务（Celery）

- 长任务（解析 / 向量化 / 重建索引）一律进 Celery，禁止在请求线程里跑
- 任务必须幂等：同一输入重放结果一致
- 任务状态写 MySQL（`ingest_jobs`），前端轮询，不依赖 Celery result backend 作为真相来源

## 日志

- 用 `structlog` 或标准库 `logging` + JSON formatter
- 每请求注入 `request_id`，日志自动带上
- **禁止**记录：密钥、token、完整文档正文、用户密码

## 配置

- 全部走 `core/config.py` 的 Pydantic `BaseSettings`，从环境变量读取
- 禁止在代码中硬编码地址、模型名、阈值
- 阈值类参数（top_k、chunk size、超时）必须可配

## 测试

- `pytest` + `pytest-asyncio`
- 测试文件位于 `backend/tests/`，镜像 `app/` 目录结构
- 领域层纯函数：直接单测，不启服务
- 集成测试：用真实 MySQL（独立 test 库）+ 真实 Milvus（独立 database），容器内跑
- 外部 HTTP 依赖用 `respx` / `httpx.MockTransport` 拦截，禁止打真实 DashScope / MinerU

## 质量

- `ruff check` + `ruff format` 零告警
- `mypy --strict`（领域层）/ 其余模块至少非 strict 通过
- 新增公开端点必须同步 OpenAPI 描述（`summary` + `response_model`）
