## Context

- 已归档 `knowledge-base`：知识库（权限与检索隔离单元）记录了 `embedding_model` / `embed_dim`；上传文档必须归属某个知识库，且只有对库持有 `EDITOR` 或 `KB_ADMIN` 的用户才能上传
- 已归档 `rag-orchestration`：检索消费的原料是「切分后的 chunk」；而 `RetrievedChunk.content` 来自切分器（后续 `chunking` change）——本 change 只负责提供切分器要吃的 **`content_list.json`**，不产出 chunk
- 既有约定：软删用 `deleted_at` + 全局查询过滤（`BaseModel`）；枚举存字符串（大写 snake）；主键 UUID v7 存 `BINARY(16)`；错误码统一信封；长任务进 Celery 且**状态写 MySQL 为真相来源**；密码/令牌类配置 `Field(repr=False)`
- Milvus 的 pk 复用 chunk 的 UUID —— 那是后续 `embedding-ingest` 的事，本 change 不涉及向量库

## Goals / Non-Goals

**Goals:**

- 「上传的文件 → 落盘 → MinerU 解析 → `content_list.json` 落盘」的最小可用闭环
- 文档生命周期可查询、可追踪：状态机 + `ingest_jobs` 进度；解析失败保留错误信息
- 格式白名单 + 文件大小限制 + 库内哈希去重，杜绝垃圾与重复入库
- 为切分/向量化 change 提供**稳定原料契约**（`content_list.json`）与可复用的存储抽象

**Non-Goals:**

- 切分（`domain/chunking` L0–L5，含父子块、overlap）——独立 change
- 向量化与 Milvus 写入、collection schema——`embedding-ingest` change
- 重建索引（reindex）/ 对账任务扫孤儿——后续 ops change
- 问答端点与引用渲染——`qa` change
- 前端上传界面——前端 change
- 多文件批量打包上传（一期逐文件提交）

## Decisions

### D1. 文档状态机只覆盖解析段，单 `status` 列直表达

**选择**：`documents.status ∈ {UPLOADED, PARSING, PARSED, FAILED}`；上传即 `UPLOADED`，解析中 `PARSING`，成功/失败 `PARSED` / `FAILED`。展示层用 `ingest_jobs` 的 progress 表达「全景」。

**理由**：project 状态机 `UPLOADED→PARSING→PARSED→CHUNKING→EMBEDDING→READY/FAILED` 是跨多个 change 的全景。本 change 只实现解析段；后续 change 追加枚举值时需评估存量兼容（`database-conventions.md`）。**不加**中间的空状态（如 `READY`），避免现在猜未来字段。

### D2. `ingest_jobs` 从上传即建，与文档 1:1；本 change 只推进到 `PARSED`

**选择**：上传事务内创建 `document`（`UPLOADED`）与其 `ingest_job`（`PENDING`，总进度 total 未知→解析后回填）。解析任务把 job 置 `RUNNING` → `SUCCESS`，文档置 `PARSED`；失败两者同步置 `FAILED`。

**理由**：`ingest_jobs` 是入库全链路的「一次入库任务」真相来源（既有规约）。上传点一次建好 job，后续 `chunking` / `embedding-ingest` 只是继续推进同一 job 的 stage/progress，不必重建记录。

### D3. 哈希去重作用域 = 知识库内

**选择**：库内已有**活跃**（未软删）且**成功解析（PARSED）**的文档与本次上传 `SHA-256` 相同 → 返回 409 `conflict`。跨库不去重（两库内容可能各有用意）。软删文档不参与去重（重新上传允许）。

**理由**：知识库是数据隔离单元；同哈希在库内重复没有价值。留「PARSED」门槛避免解析失败的重试被误判为重复。

### D4. 文件存储抽象 `FileStorage`，本 change 落盘本地文件系统

**选择**：`FileStorage` 定义 `save_raw(stream, rel_path)` / `open_raw` / `save_artifact` / `open_artifact` / `delete` 等，本地实现按 KB + 文档 id 组织目录：`<root>/<kb_id>/<document_id>/raw.<ext>` 与 `.../content_list.json`。接口可切 MinIO（`project.md` 明确）。

**理由**：`project.md` 把文件存储定为「本地 fs、接口可切 MinIO」。本 change 只交本地实现；接口签名保证切换不污染业务层。

### D5. MinerU 集成走云 API v4，HTTP 直连、显式超时、`content_list.json` 为唯一产物

**选择**：`integrations/mineru.py` 封装云 API v4：`POST` 提交文件 → 轮询任务 → 下载 `content_list.json`。`model_version=vlm`、超时显式可配（`MINERU_TIMEOUT_SEC`）。raw 第三方异常包装为内部 `UpstreamError`（映射 503 `upstream_unavailable`）。

**理由**：本机无 GPU（project 环境现状），本地 MinerU `pipeline` 后端精度低且与重负载冲突——云 API 是默认路径。HttpX 直连而非 SDK，与 `rag-orchestration`「DashScope 不装 SDK」同一取向；超时/包装按 `backend-conventions` 外部集成铁律。

### D6. 解析任务幂等：状态是重放护栏，任务分支按当前状态

**选择**：`document_parse` 入口校验文档状态：非 `UPLOADED` 直接按现状返回（已 `PARSED` = 幂等成功、`FAILED` = 不重放/按需）。同一 id 的并发重放由 Celery 单 worker 串行 + 状态检查兜底。

**理由**：既有规约要求长任务幂等、`ingest_jobs` 状态为真相。状态本身即幂等键——比引入去重 UUID 更直白。

### D7. 上传权限 = 对库持 `EDITOR` 或 `KB_ADMIN`；`VIEWER` 403

**选择**：上传/软删校验库级角色；`VIEWER` 一律 403 `access_denied`。列表/详情校验「可访问该库」（任意授权角色）。

**理由**：`knowledge-base` 已定角色语义（`EDITOR` 管文档、`VIEWER` 仅读），本 change 落实业务动作边界；复用既有 `require_kb_role` 依赖与错误码。

### D8. 格式白名单与大小限制为配置，前端仅提示不做边界

**选择**：白名单收敛为 MinerU 云端 API 真正支持的 `pdf / docx`（对应 project「PDF / Word」）；`UPLOAD_MAX_SIZE_MB`（默认 50）超过返回 413 `file_too_large`，扩展名不识别返回 415 `unsupported_file_type`。校验以**服务端**为准。

**理由**：MinerU 云端 v4 实际只接受 pdf / 图片 / doc / docx / ppt / pptx / html——**不接受 Markdown**。若按原稿误收 `md`，会在真实解析时于上游 503/失败，白给用户坏体验。Markdown（本就纯文本，无需扫描排版）与图片（project 二期非向量化）留待后续 change 走本地/专用路径。

## Risks / Trade-offs

- **MinerU 云 API 依赖可用性**：网络/鉴权/上游故障时解析失败 → 文档 `FAILED` + `error_message` 保留，可重试上传。不做静默重试循环（避免重负载叠加，project 内存紧张）；重试由用户重新触发上传走新 job
- **哈希去重门槛（PARSED）下**重试上传会因旧 FAILED 文档不占去重 → 新建文档，可能累积 FAILED 记录 → 后续提供清理任务（ops change）
- **Ingest job 与文档状态双写可能瞬时不一致**：用同一事务提交（上传）与同一任务内同步更新（解析）缓解；跨任务崩溃以 job 状态为准，提供校正入口
- **Celery 未配置 worker**：上传只建记录、job 停在 `PENDING`，文档停在 `UPLOADED`——本地开发需起 worker。接受（见 Migration 与实施期决策 3）
- **迁移风险**：新增两张表，无存量数据；枚举用字符串列 + 约束校验

## Migration Plan

1. Alembic 迁移建立 `documents` 与 `ingest_jobs`
2. `FileStorage` + `MinerU` 集成层实现并单测（MockTransport，不打真实云 API）
3. 模型/服务层 + 解析任务实现
4. 上传/列表/详情/软删路由 + 权限接线
5. 配置项补入 `config.py` 与 `.env.example`（`STORAGE_ROOT` / `MINERU_*` / `CELERY_BROKER_URL` / `UPLOAD_MAX_SIZE_MB`）
6. 无数据迁移（新表）

## Open Questions

- **切分/向量化阶段如何续用同一 `ingest_job`**：本 change 只到 `PARSED`；`chunking` / `embedding-ingest` 复用 job 记录推进 stage，还是新建二级 job —— 留给切分 change 定稿，本 change 不为它预留字段
- **MinerU 云 API 分页/批量**：一期单文件提交，不做批处理
- **`content_list.json` 的 schema 版本**：以上游返回为准，本 change 不定义 Block 数据契约（属 `chunking` change）

## 实施期决策（签字确认）

1. **上传即占位 job、progress 解析后回填**：`total` 在上传时未知，置 0，解析成功页数回填（MinerU 返回的页数/块数）。进度仅「定性」展示（解析中/完成），不承诺精确百分比。
2. **软删文档语义**：`DELETE` 只做软删（`deleted_at`），不物理删文件、不建 `chunks`（本 change 无向量可清）。解析产物清理归 ops 对账任务。
3. **本地开发 worker 说明**：上传后需 `uv run celery -A app.tasks worker` 才推进到 `PARSED`；未起 worker 时文档停在 `UPLOADED`、job 停在 `PENDING`（符合「状态为真相」语义），`.env.example` 补充注释。
4. **不新增枚举「READY」**：文档解析完成即 `PARSED`（非最终 READY）；`READY` 语义留给向量化完成后定义，避免现在误标。
5. **列表/详情暂不分页**：一期文档量小；待有规模或前端需要时再加游标/总数信封（`knowledge-base` 同类决策）。