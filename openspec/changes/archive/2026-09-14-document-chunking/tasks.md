## 1. 数据层：chunks 模型 + 枚举追加 + 迁移（TDD）

- [x] 1.1 红灯：迁移测试——`alembic upgrade head` 后 `chunks` 表存在且含约束（`kb_id`/`document_id` FK、`parent_id` 自关联、`content` Text、`bbox` JSON、`is_recallable` bool）；`documents.status` 枚举允许 `CHUNKING`
- [x] 1.2 新建 `backend/app/models/chunk.py` 的 `Chunk` 模型（UUID v7 主键、软删 mixin、`is_recallable`、`section_path`、`page_idx`、`bbox` JSON 容错读取、`parent_id` 自引用），并在 `app/models/__init__.py` 导出
- [x] 1.3 写 Alembic 迁移：建 `chunks` + `documents.status` 枚举列 MODIFY（追加 `CHUNKING`），`downgrade` 可回滚（删表 + 还原枚举）；`alembic heads` 唯一
- [x] 1.4 绿灯：`uv run pytest` 迁移/模型用例通过；`ruff` + `mypy app` 零错误

## 2. 纯域切分：domain/chunking（TDD 主战场）

- [x] 2.1 红灯：`blocks_from_artifact`——给定 fixture `content_list.json`，解析为 `list[Block]`，`text_level`/`page_idx`/`bbox`/`type` 正确；坏 JSON 抛 `ValueError`
- [x] 2.2 红灯：`build_chunks(blocks, cfg)` 确定性——同输入两次输出逐块相等；按类型档位贪心打包，长文本段→句→子句降级，`table/code/equation` 原子独立成块不跨父节点
- [x] 2.3 红灯：表格双表示（口语化摘要 + Markdown 原文）与公式 LaTeX/代码原文保留；面包屑（Section Path）注入 child 前缀
- [x] 2.4 红灯：父子块 small-to-big——业务块产出 recallable child + parent，`parent_id` 关联正确；无层级语境块自身即父（`parent_id` 为空可索引）
- [x] 2.5 实现 `domain/chunking/`（Block/Chunk dataclass、`TokenCounter` 可插拔、`ChunkConfig`），全零 I/O 纯函数；`pytest` 毫秒级全绿 + `mypy --strict` 通过

## 3. 服务层与落库：chunk_service + 状态机（TDD）

- [x] 3.1 红灯：`chunk_service` 切分驱动——`PARSED` 文档置 `CHUNKING`（job `RUNNING`, stage `CHUNK`），切分产出 child+parent 事务内落 `chunks`，完成后回 `PARSED`（job `SUCCESS`, stage `CHUNK`）
- [x] 3.2 红灯：幂等——对已切分（`PARSED` 且已有 `chunks`）文档重放不产生重复 chunks、不再切分；`FAILED` 不重放副作用
- [x] 3.3 红灯：失败——切分异常文档置 `FAILED`、error 保留、不留半套 chunks（事务回滚）
- [x] 3.4 红灯：软删接线——`DELETE /documents/{id}` 同事务软删 document + 其全部 `chunks`；重复软删幂等
- [x] 3.5 实现 `services/chunk_service.py`，软删逻辑并入既有 `document_service`；列表/详情响应层展含切分进度
- [x] 3.6 绿灯：`pytest` 全绿；`chunks.content` 列表路径用 `load_only` 排除大字段

## 4. Celery 切分任务链（TDD）

- [x] 4.1 红灯：切分任务——`PARSED` 文档切分并落 `chunks`；已切分/`FAILED` 短路幂等
- [x] 4.2 红灯：`document_parse`（既有）成功后触发切分任务分派（task 编排），`IngestJob` 全程为其真相且 `stage` 推进
- [x] 4.3 实现 `tasks/ingest.py` 扩展；`ruff` + `mypy app` 零错误（含对 `app.tasks.*` 的既有 mypy 覆盖保持一致）

## 5. 配置与环境

- [x] 5.1 `domain/chunking` 的 `ChunkConfig` 从 Settings 组装（text/table/code/equation/list 各 target/max、`overlap_ratio` 默认 0 关、tiktoken 计数）
- [x] 5.2 补 `config.py` 字段（`CHUNK_*`）与 `.env.example`；阈值不硬编码

## 6. 门禁 + 收尾

- [x] 6.1 `uv run pytest` 全绿、`uv run ruff check .` 与 `uv run mypy app`（领域层 `--strict`）零错误
- [x] 6.2 集成验证一次上传→PARSED→CHUNKING→PARSED（含 chunks 落库）；软删后文档与 chunks 均不出现在列表/二次查询
- [x] 6.3 delta specs 已覆盖全部实现行为；`openspec validate --strict` 通过
- [x] 6.4 归档 `openspec/changes/document-chunking/` → `openspec/changes/archive/<date>-document-chunking/`，主 spec 二文件（chunking/documents）合入；同步 `openspec/project.md` 状态机语义（`PARSED` 复用为"解析+切分完成、索引原料就绪"）与切分期转说明