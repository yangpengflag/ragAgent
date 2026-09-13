# Proposal: wire-tracing-at-startup

## Why

`rag-orchestration-langchain` 交付了观测开关 `apply_tracing_config()`，但**从未在应用启动时调用**——`create_app()` 与 `lifespan()` 都没有它。结果是：即使配置了 `LANGSMITH_TRACING=true` 与上报目标，观测也完全不生效，开关是死代码。

这是"实现遗漏"而非设计取舍：spec 要求"观测默认关闭且可多粒度开启"，而"可开启"这一支从未被接通。测试没抓到，因为既有用例只验证函数本身，没有"启动后进程环境应被校正"的断言。

## What Changes

- `create_app()` 在启动期调用 `apply_tracing_config(settings)`：配置齐全 → 置 `LANGSMITH_TRACING=true`；配置不全或关闭 → 置 false 并清除目标与凭证（防止误报出网）
- 启动日志记录一次观测开关的最终状态（便于排障"到底开没开"）
- 新增启动期断言测试，覆盖"齐全/不全/关闭"三种形态

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `rag-orchestration`：「观测追踪默认关闭且可多粒度开启」补充"启动时按配置装配"的行为与场景

## Impact

- **代码**：`backend/app/main.py`（一处调用 + 一行日志）
- **测试**：`backend/tests/test_app_factory.py` 新增启动期断言
- **兼容性**：默认关闭，行为不变；已配置观测的环境才会真正开始上报
- **非目标**：不接线请求级 `tracing_context`（归 QA 端点 change），不改 fail-open 语义
