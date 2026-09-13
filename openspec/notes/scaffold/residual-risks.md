# project-scaffold 残留风险清单

> 来源：`project-scaffold` 完成后的独立 Spec 评审（2026-09-12）。
> 这些**不阻塞骨架放行**，但后续 change 触及相关能力时**必须先处理**。
> 本文档为工程 brief，不参与 OpenSpec 工作流。

## 1. SSE 流式响应会丢 request_id ⚠️ 优先级最高

`app/core/request_id.py` 在 `call_next` 返回后立即 `reset()` contextvar，
而流式响应的响应体是**在其后**由生成器迭代输出的。
后果：生成器内部发出的日志拿不到 `request_id`；
`"request handled"` 日志记录的是"流开始"而不是"流结束"。

**首个 `chat/stream`（SSE）change 必须改**：把 reset 放进生成器的 `finally`，
或把 `request_id` 显式注入生成器闭包。

## 2. 成功响应体的 request_id 需逐端点写

当前只有 `/api/v1/health` 写了 `request_id`。
`api-conventions.md` 要求所有成功响应都带该字段。
**首个业务端点前**应补一个响应包装/依赖，避免逐处遗漏。

## 3. 500 响应缺 CORS 头

未处理异常由最外层的 `ServerErrorMiddleware` 直接产出响应，绕过 `CORSMiddleware`，
浏览器侧读不到 500 的响应体。**首个前端联调前**需评估：
考虑自定义外层中间件补 CORS 头，或接受该限制并在前端做通用错误兜底。

## 4. WebSocket 无 request_id

`RequestIdMiddleware` 继承 `BaseHTTPMiddleware`，对 `scope["type"] != "http"` 直接透传。
**若引入 WebSocket**（如实时进度推送），需单独的中间件。

## 5. 软删的已知坑（首个业务实体 change 一并处理）

`BaseModel` 只提供 `deleted_at` 字段与 `soft_delete()`，**未注册全局查询过滤**（刻意的 YAGNI）。
引入查询时必须一次性处理：

- 加全局 `with_loader_criteria` 或强制显式 `deleted_at IS NULL`，否则 `select`/`session.get` 会返回已删行
- **唯一约束要兼容软删**（否则删后无法重建同名记录）：改用部分唯一索引，或把 `deleted_at` 纳入唯一键
- `soft_delete()` 只改字段，不 flush/commit、不级联清 Milvus 向量 —— 按 `database-conventions.md`「删除必须清向量」，须在 service 层编排
- 为 `deleted_at` 补索引
- `soft_delete()` 目前**非幂等**（重复调用覆盖时间戳），且无 `restore()`

## 6. UUID 与 hex 互转工具尚未提供

D7 明确推迟到首个业务实体 change（届时日志需要以 hex 输出 UUID）。
同时补 `tests/test_ids.py` 之外的互转单测。

## 7. `.env.example` 与本 change 的配置面不一致

`.env.example` 里 DashScope / MinerU / 切分 / 检索 / JWT / 限流等键**当前无消费者**（`extra="ignore"` 忽略）。
首个消费它们的 change 需确认键名映射无误，并在 `Settings` 补声明与测试。

## 8. `app_debug` 字段暂无消费者

默认已改为 `False`（debug 会绕过异常处理器）。若将来要用它控制文档/调试端点，
必须同时确保**不传给 `FastAPI(debug=...)`**——原因见 `design.md` D6。

## 9. 测试库名必须以 `_test` 结尾

`backend/alembic/env.py` 的守卫要求：`ALEMBIC_TARGET=test` 时解析出的库名必须以 `_test` 结尾，否则 `RuntimeError`。
若将来改用别的测试库命名（如 `ragagent_it`），**必须同步修改守卫与 `MYSQL_TEST_DATABASE`**。

## 10. Milvus 探针的线程与内存换算要留意

卡住的探测线程**无法被取消**（Python 限制），因此实现做了三层约束，改动时不要拆掉任何一层：

- **在飞标记带代次 token**：陈旧接管后，旧线程返回时不会误清新线程的标记
- **`MAX_LIVE_WORKERS = 2` 硬上限**：依赖长期不可达时最多累积 2 个卡住线程；达到上限后健康检查直接返回 `down`（原因 `probe workers exhausted`），不再新建
- **陈旧窗口 `max(5×timeout, 30s)`**：超过即允许接管，保证依赖恢复后能重新探测

若将来把窗口调大或上限调小，需同步复核 `test_health_probes.py` 的三条用例。
另注意：`MilvusClient()` **构造本身就是建连**（不可达时约一个 timeout 后抛错），因此构造放在 `MilvusProbe.__init__` 里预热、不占探测的计时预算。

## 11. 测试目录仍为平铺

`backend/tests/` 目前平铺。按约定，**首个业务模块落地时**改为 `tests/<层>/` 镜像 `app/` 结构。
