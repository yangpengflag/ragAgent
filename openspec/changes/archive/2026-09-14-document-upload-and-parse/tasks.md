> TDD 顺序：每节先红灯（写失败测试）→ 绿灯（实现）→ 重构。本节任务按依赖分批，与 `design.md` 决策 D1–D8 对齐。

## 1. 数据层（红灯优先）

- [x] 1.1 红灯：写模型测试——`Document` 默认状态 `UPLOADED`；软删文档被全局过滤
- [x] 1.2 绿灯：`Document` 模型（`kb_id` 外键、`filename`、`file_hash`、`file_size`、`content_type`、`status` 枚举、`page_count`、`error_message`、`raw_path`、`artifact_path`）+ Alembic 迁移。实测坑：外键列类型必须用项目 `GUID`（`sa.Uuid()` 触发 MySQL error 3780），沿用 `b7e3c1` 教训
- [x] 1.3 红灯：写模型测试——`IngestJob` 默认 `PENDING`；`document_id` 外键唯一
- [x] 1.4 绿灯：`IngestJob` 模型（`document_id` FK、`kb_id`、`stage`、`status`、`progress_current`/`progress_total`、`error`、`started_at`/`finished_at`）+ 迁移

## 2. 存储与解析集成

- [x] 2.1 红灯：用 `tmp_path` 写 `FileStorage` 本地实现测试——`save_raw` / `open` 往返字节一致；路径含 kb_id/document_id；`save_artifact` 独立目录
- [x] 2.2 绿灯：`FileStorage` 接口 + `LocalFileStorage`（目录 `<root>/<kb_id>/<document_id>/`）
- [x] 2.3 红灯：用 `httpx.MockTransport` 写 `MineruClient` 测试——提交→轮询成功→下载 `content_list.json`；超时与 HTTP 错误抛内部 `UpstreamError`；轮询超上限抛失败
- [x] 2.4 绿灯：`MineruClient`（云 API v4，`model_version=vlm`，显式超时，`UpstreamError` 包装）
- [x] 2.5 红灯：配置测试——`config.py` 新增项缺失/非法的 fail-fast 与 `repr` 隐藏（key 类字段）
- [x] 2.6 绿灯：`config.py` 增补 `STORAGE_ROOT` / `MINERU_ENDPOINT` / `MINERU_API_KEY`(repr=False) / `MINERU_MODEL_VERSION` / `MINERU_TIMEOUT_SEC` / `CELERY_BROKER_URL` / `UPLOAD_MAX_SIZE_MB`，`.env.example` 同步

## 3. 文档与服务层

- [x] 3.1 红灯：写服务测试——创建文档（权限预检在路由层，服务只做哈希去重/大小/类型校验）；库内活跃 `PARSED` 同哈希 → 409 `conflict`；格式不支持 415；超限 413；软删文档不参与去重
- [x] 3.2 绿灯：`document_service.create_document`（哈希去重、类型/大小校验、建 `Document`+`IngestJob` 于同一事务）
- [x] 3.3 红灯：写解析编排测试——状态机推进 `UPLOADED→PARSED` / `UPLOADED→FAILED`；置 `PARSED` 前先落盘产物；job 同步更新；对非 `UPLOADED` 文档重放幂等
- [x] 3.4 绿灯：`document_service.resolve` / 状态推进 + `mineru` 编排
- [x] 3.5 红灯：写列表/详情/软删查询测试——列表排除软删、按库过滤、附带 job 状态；软删标记式
- [x] 3.6 绿灯：列表/详情/软删服务方法

## 4. Celery 任务

- [x] 4.1 红灯：写任务测试——`document_parse.delay` 在非 `UPLOADED` 时短路（幂等）；`RUNNING`→`SUCCESS` 推进；异常时文档与 job 均 `FAILED` 且记错误
- [x] 4.2 绿灯：`app/tasks/ingest.py` 定义 `document_parse` 任务（幂等、状态为真相、错误兜底写库）
- [x] 4.3 绿灯：Celery app 装配（broker 指向 Redis，配置来自 `config.py`）；`uv run celery -A app.tasks worker` 可起

## 5. HTTP 接口

- [x] 5.1 红灯：写路由测试——上传 multipart 的成功/415/413/409/403/404 状态码与响应信封；`require_kb_role`（`EDITOR`/`KB_ADMIN`）接线
- [x] 5.2 绿灯：`POST /api/v1/knowledge-bases/{kb_id}/documents`（multipart）+ `schemas/document.py`
- [x] 5.3 红灯：写路由测试——列表/详情/软删接口的状态码、权限（可访问 vs 管理）与响应形状
- [x] 5.4 绿灯：列表/详情/软删路由 + 注册到 `router.py`

## 6. 门禁与收尾

- [x] 6.1 `uv run pytest` 全绿、`ruff check .` 与 `mypy app` 零错误
- [x] 6.2 前端不受影响（无前端改动）；确认 `openspec/notes/` 无需新增 brief
- [x] 6.3 同步 `openspec/specs/documents/spec.md` 并归档本 change