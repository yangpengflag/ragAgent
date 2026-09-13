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

## 2. 成功响应体的 request_id 需逐端点写 ✅ 已处理（`auth-and-users` §2）

原先只有 `/api/v1/health` 手工带 `request_id`。已落地：

- `app/schemas/base.py::ApiResponse` —— 成功响应基类，`request_id` 为**必填**（漏传在构造期即失败）
- `app/api/deps.py::current_request_id` —— 取当前请求标识的依赖
- `/api/v1/health` 已收敛到该基类，响应形状保持不变（有测试锁定）

新端点只需继承 `ApiResponse`；`tests/test_api_response.py` 守住了形状与一致性。

## 3. 500 响应缺 CORS 头 ✅ 已处理（`auth-and-users` §7.7）

Starlette 的 `ServerErrorMiddleware` 位于所有中间件之外，未处理异常产出的 500
会绕过 `CORSMiddleware`，浏览器读不到错误体。已修复：`app/main.py` 新增
`UnexpectedErrorMiddleware`（注册在 CORS **之前**，CORS 包在其外层），把未处理
异常转成统一 500 信封，向外穿过 CORS 时自动补响应头。测试锁定：
`tests/test_unexpected_error_cors.py`（500 信封 + CORS 头 + 无 Origin 不加头 +
堆栈只进日志）。

## 4. WebSocket 无 request_id

`RequestIdMiddleware` 继承 `BaseHTTPMiddleware`，对 `scope["type"] != "http"` 直接透传。
**若引入 WebSocket**（如实时进度推送），需单独的中间件。

## 5. 软删的已知坑（首个业务实体 change 一并处理）——部分已处理（`auth-and-users` §2/§3）

已在 `auth-and-users` §2 落地：

- ✅ **全局查询过滤**：`app/models/base.py` 注册 `do_orm_execute`，为所有 ORM SELECT 附加 `deleted_at IS NULL`
  （实测 `Session.get()` 同样被过滤，非假设）；逃生通道为**语句级**执行选项 `include_soft_deleted`
- ✅ **`deleted_at` 补索引**
- ✅ **`soft_delete()` 改为幂等**（重复调用不覆盖首次删除时间）

仍待处理：

- ✅ **唯一约束兼容软删**（`auth-and-users` §3 落地）：MySQL 不支持部分索引（`WHERE deleted_at IS NULL`），改用等价方案——虚拟生成列 `username_active = CASE WHEN deleted_at IS NULL THEN username ELSE NULL END` + 唯一索引 `uk_users_username_active`（软删行该列为 NULL，唯一索引允许多个 NULL）；SQLite 单测与 MySQL 集成测试（`information_schema` 校验 + 同名软删重建全链路）双重锁定。**后续每个带业务唯一键的表照此办理**
- ⏳ **`soft_delete()` 不 flush/commit、不级联清 Milvus 向量** —— 文档类实体的删除编排（清向量 + 对账）随文档能力引入
- ❌ **`restore()`**：本期明确不做（仅启用/停用），软删记录仅用于审计追溯

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
