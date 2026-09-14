## 1. 数据层：文档状态枚举追加（TDD）

- [x] 1.1 红灯：迁移测试——`alembic upgrade head` 后 `documents.status` 枚举允许 `EMBEDDING/READY`
- [x] 1.2 更新 `backend/app/models/document.py` 的 `DocumentStatus` 追加 `EMBEDDING/READY`；写 Alembic 迁移 MODIFY 该枚举列，`downgrade` 可回滚（还原枚举）；`alembic heads` 唯一
- [x] 1.3 绿灯：`pytest` 迁移用例通过；`ruff` + `mypy app` 零错误

## 2. Milvus 集成：显式建表 + 删除（TDD）

- [x] 2.1 红灯：`ensure_collection(settings)`——collection 不存在时按约定 schema 显式创建（`chunk_id` 主键 auto_id=False、`content`、`vector`【FloatVector dim=embed_dim】、`kb_id` partition、`document_id`）；已存在幂等返回
- [x] 2.2 红灯：`delete_document_vectors(settings, kb_id, document_id)`——按 expr（`document_id == ... and kb_id == ...`）删除该文档全部向量，删空幂等成功、无异常
- [x] 2.3 实现 `integrations/milvus.py`（pymilvus 直连负责建表/删除）；`vectorstore.py` 写入侧显式禁用自动建表
- [x] 2.4 绿灯：Mock/独立测试 database 下用例通过；`ruff` + `mypy` 零错误

## 3. 服务层：状态机推进 + 失败补偿（TDD）

- [x] 3.1 红灯：`index_service` 向量化打单——`PARSED` 且含 `is_recallable` chunk 的文档置 `EMBEDDING`（job `RUNNING`, stage `EMBED`），先幂等清旧向量再编码写 Milvus，成功置 `READY`（job `SUCCESS`, stage `EMBED`）
- [x] 3.2 红灯：幂等与重放——写前清旧向量不残留重复存活 chunk_id；对已 `READY`/进行中文档重放短路；`document_id` 可辨识已写向量
- [x] 3.3 红灯：失败——编码/写入异常文档置 `FAILED`、error 保留
- [x] 3.4 红灯：软删接线——`DELETE /documents/{id}` 事务内软删 document+chunks，提交后清 Milvus 向量；清向量失败不阻塞软删、记日志；重复软删幂等
- [x] 3.5 实现 `services/index_service.py`，软删清理并入既有 `document_service`；列表/详情响应层展含索引阶段（`EMBEDDING/READY`）
- [x] 3.6 绿灯：`pytest` 全绿

## 4. Celery 向量化任务链（TDD）

- [x] 4.1 红灯：向量化任务——已就绪（`PARSED` 且含 child chunk）文档编码写 Milvus → `READY`；非就绪/已 `READY`/`FAILED` 短路幂等
- [x] 4.2 红灯：任务编排——`document_parse`/切分任务成功后触发向量化任务分派，`IngestJob` 全程为其真相且 `stage=EMBED`
- [x] 4.3 实现 `tasks/ingest.py` 扩展；`ruff` + `mypy app` 零错误（结合既有 `app.tasks.*` mypy 覆盖保持一致）

## 5. 配置与环境

- [x] 5.1 补 `config.py` 的 `MILVUS_TIMEOUT_SEC`（显式超时）；`embed_dim/model/batch` 沿用既有 `dashscope_embed_*`，不重复定义
- [x] 5.2 `.env.example` 补新增项；敏感项不硬编码

## 6. 门禁 + 收尾

- [x] 6.1 `uv run pytest` 全绿、`uv run ruff check .` 与 `uv run mypy app` 零错误
- [x] 6.2 集成验证一次上传→PARSED→CHUNKING→PARSED→EMBEDDING→READY（本地 MySQL/Milvus/worker 起全链）或标注环境无法验证项；软删后检索不含该文档
- [x] 6.3 delta specs 已覆盖全部实现行为；`openspec validate --strict` 通过
- [x] 6.4 归档 `openspec/changes/document-embedding-index/` → `openspec/changes/archive/<date>-document-embedding-index/`，主 spec 二文件（vector-index/documents）合入；同步 `openspec/project.md` 状态机语义（文档最终态 `READY` 及向量化段转说明）