---
trigger: always_on
---
# API 规约

定义前后端接口契约。以下为 SHOULD 级约定。

## URL 结构

- 格式：`/api/v1/<resource>[/<id>][/<action>]`
- resource 用 **snake_case 复数**：`/api/v1/knowledge_bases`、`/api/v1/documents`
- action 用 kebab-case：`/api/v1/documents/{id}/reindex`
- 资源操作优先用 HTTP 动词语义，动词无法表达时才加 action

## 成功响应

所有成功响应带 `request_id` + 业务字段：

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "id": "018e53ad-...",
  "name": "差旅制度库"
}
```

- `request_id`：中间件生成，贯穿日志与响应，用于追踪
- 业务字段统一 **snake_case**
- 状态码：200 查询/操作成功、201 创建成功、204 无内容

## 错误响应

```json
{
  "request_id": "550e8400-...",
  "error_code": "access_denied",
  "message": "You do not have access to this knowledge base",
  "details": { "kb_id": "018e53ad-..." }
}
```

- `error_code`：语义化 snake_case，前端据此分支
- `message`：面向用户的英文描述（不泄漏内部堆栈）
- `details`：可选，字段级或上下文信息

## 错误码

| HTTP | 场景 | error_code |
|---|---|---|
| 401 | 未认证 / token 失效 | `unauthorized` / `token_expired` |
| 403 | 越权 | `access_denied` |
| 404 | 资源不存在 | `not_found` |
| 409 | 状态冲突（如文档未 READY 就问答） | `conflict` |
| 413 | 文件过大 | `file_too_large` |
| 415 | 格式不支持 | `unsupported_file_type` |
| 422 | 校验失败 | `validation_error` |
| 429 | 限流 | `rate_limited` |
| 503 | 上游不可用（MinerU / DashScope / Milvus） | `upstream_unavailable` |
| 500 | 未知错误 | `internal_error` |

## 分页

列表统一信封：

```json
{
  "request_id": "...",
  "items": [...],
  "page": 1,
  "size": 20,
  "total": 137,
  "has_more": true
}
```

- `page` 从 1 开始；`size` 默认 20，上限 100
- 文档/chunk 这类可能增长很快的列表，另提供 cursor 模式

## 异步任务

长操作（解析、重建索引）返回任务句柄，前端轮询：

```json
{
  "request_id": "...",
  "job_id": "018e53ad-...",
  "status": "RUNNING",
  "progress": { "current": 42, "total": 180, "stage": "EMBEDDING" },
  "error": null
}
```

- `status`：`PENDING` / `RUNNING` / `SUCCESS` / `FAILED`
- 前端轮询间隔 2s，终态停止
- **真相来源是 MySQL `ingest_jobs`，不是 Celery result backend**

## SSE 流式（问答）

- 端点：`POST /api/v1/chat/stream`，响应 `text/event-stream`
- 事件类型：
  ```
  event: token      data: {"delta": "根据"}
  event: citation   data: {"index": 1, "document_id": "...", "chunk_id": "...", "page": 12}
  event: done       data: {"message_id": "...", "usage": {...}}
  event: error      data: {"error_code": "...", "message": "..."}
  ```
- 先发 `citation`，再发 `token`，最后 `done` —— 前端先渲染引用再流式出正文
- 心跳：每 15s 发 `: ping` 注释行保活

## 鉴权

- `Authorization: Bearer <access_token>`
- access token 15 分钟；refresh token 7 天，httpOnly cookie
- 401 时前端自动刷新并重放一次，失败则跳登录

## 序列化约定

- 后端 JSON 字段：snake_case
- 前端 TS 类型字段：同为 snake_case，不做转换层
- 时间字段：ISO 8601 UTC 字符串，字段名以 `_at` 结尾

## 权限语义

- 所有知识库相关端点必须校验 `user_kb_grant`
- 越权一律 403（`access_denied`）；不存在的资源对无权限用户也返回 403（避免探测存在性）
