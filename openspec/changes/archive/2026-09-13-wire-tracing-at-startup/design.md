## Context

`integrations/tracing.py::apply_tracing_config()` 的职责是把 Settings 的生效判定写回进程环境——LangSmith SDK 以环境变量为唯一开关来源，所以"装配"就是"校正 env"。该函数有单元测试，但没有任何调用点。

`create_app()` 的启动顺序里已有 `load_settings()` → `configure_logging()`，观测装配应与它们同级：都在"进程级一次性副作用"这一类里。

## Goals / Non-Goals

**Goals:**

- 让观测开关在启动时真正生效（配置齐全才开）
- 启动日志能回答"观测到底开没开"，避免排障靠猜
- 用启动期断言防止再次漏接

**Non-Goals:**

- 不做请求级 tracing（QA 端点 change）
- 不引入 SDK 客户端显式构造（SDK 以 env 为源，保持一致）
- 不在测试里真的联网（只断言 env 最终态）

## Decisions

### D1: 在 `create_app()` 里调用，而不是 `lifespan`

**选择**：`create_app()` 中 `configure_logging(settings)` 之后调用。

**理由**：env 必须在**任何请求处理之前**就位；`lifespan` 在应用构造完成后才触发，若其间有模块级初始化读取 env 会漏掉。且 `create_app()` 是测试可直接调用的最小装配入口，断言成本低。

### D2: 日志只记开关状态，不记目标与凭证

**选择**：`logger.info("observability configured", tracing=... )`，不带 endpoint/key。

**理由**：凭证信息不进日志（与 scaffold 的敏感字段约定一致）；排障只需知道开/关与原因（配置不全 vs 已启用）。

## Risks / Trade-offs

- **测试按顺序修改进程 env 可能相互污染** → 用例内显式清理相关变量后再断言，并在 `afterEach` 还原。
- **开启观测后业务数据会出网** → 默认关闭不变；本次只是让"已显式配置"的场景真正生效，与 spec 的"出网目标受配置约束"一致。

## Migration Plan

单行调用 + 日志 + 新增测试。无数据迁移、无配置变更。回滚 = 移除调用。

## Open Questions

（无。）
