## 1. 红灯

- [x] 1.1 红灯：启动应用且观测配置齐全 → 进程环境 `LANGSMITH_TRACING` 为 `true`
- [x] 1.2 红灯：启动应用且配置不全（缺 endpoint）→ `LANGSMITH_TRACING` 为 `false`，且目标/凭证被清除
- [x] 1.3 红灯：启动应用且未配置观测 → `LANGSMITH_TRACING` 为 `false`，不残留目标/凭证

## 2. 绿灯

- [x] 2.1 `create_app()` 调用 `apply_tracing_config(settings)`
- [x] 2.2 启动日志记录观测开关最终状态（不含目标与凭证）

## 3. 门禁与收尾

- [x] 3.1 `uv run pytest` 全绿、`ruff check .` 与 `mypy app` 零错误
- [x] 3.2 同步 `openspec/specs/rag-orchestration/spec.md` 并归档本 change
