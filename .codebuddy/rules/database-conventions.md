---
trigger: always_on
---
# 数据库规约

后端使用 **MySQL 8 + SQLAlchemy 2.0 + Alembic**。以下为 SHOULD 级约定。

## 迁移

- **所有 schema 变更必须写 Alembic 迁移**，禁止依赖 `create_all` 自动建表
- 迁移文件必须可回滚（`downgrade` 不得为空实现）
- 迁移入仓；多人协作时 `alembic heads` 唯一
- 禁止手改已提交的迁移文件

## 公共字段

所有业务表统一继承 mixin，提供：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `BINARY(16)` / UUID | 主键，应用层生成（`uuid7` 或 `uuid4`） |
| `created_at` | `DATETIME(6)` | 创建时间，不可更新 |
| `updated_at` | `DATETIME(6)` | 最后修改时间，自动更新 |
| `deleted_at` | `DATETIME(6) NULL` | 软删标记，`NULL` = 活跃 |

- 时间统一存 **UTC**，展示层转换时区
- 软删用 `deleted_at`，不用 `is_deleted` 布尔（便于审计）

## 主键策略

- 统一 **UUID**，存 `BINARY(16)`（MySQL 上比 VARCHAR(36) 省一半索引空间）
- 不使用自增主键（避免暴露业务量、便于跨库合并）
- **Milvus 的 pk 复用 chunk 的 UUID 字符串**，保证 MySQL ↔ Milvus 双向可追溯

## 命名

- 表名：**snake_case 复数**（`knowledge_bases` / `documents` / `chunks`）
- 列名：**snake_case**
- 索引：`idx_<table>_<cols>`；唯一索引 `uk_<table>_<cols>`
- 外键列：`<entity>_id`

## 枚举

- 用 `SQLEnum` 存字符串（**禁止**存 ordinal）
- 枚举值大写 snake：`READY` / `FAILED` / `PARSING`
- 新增枚举值需评估存量数据兼容性

## JSON 列

- 结构化且需要查询的字段，用普通列
- 仅整体读写、不参与查询条件的用 `JSON`（如 `chunk_config`、`citations`）
- JSON 列必须有默认值，且读取时容错（缺失键不炸）

## 查询约定

- 用 SQLAlchemy 2.0 风格 `select()`，不用 legacy `Query`
- 涉及软删的查询**必须显式过滤** `deleted_at IS NULL`
- 列表查询必须有上限，禁止无 limit 的全表扫描
- `chunks.content` 为大字段，列表查询禁止 `SELECT *`

## 一致性约束（本项目特有）

- **MySQL 与 Milvus 双写**：先写 MySQL 拿 `chunk.id`，再以同 id 作 Milvus pk；失败写 `ingest_jobs` 进补偿队列
- **删除必须清向量**：文档软删/硬删都要同步删 Milvus 中对应 pk；提供对账任务扫孤儿
- **禁止混维度**：同一 Milvus collection 内所有向量必须同 `embed_dim`、同模型；换模型须整库重建或新 collection 双写切换

## 环境

- 开发/测试库：`ekb_dev` / `ekb_test`
- 测试使用独立 database，跑完不残留（或用事务回滚）
- 禁止在测试中连开发库
