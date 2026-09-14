## Context

- 已归档 `rag-orchestration-langchain`：`retrieve(query, store, kb_ids, top_k)` 需要调用方传入**授权 kb_id 集合**；`KbAccessResolver` 面向 `KbGrantReader` 端口编程，真实实现缺失（该 change 的 Deferred 第 3 条）
- `project.md`：知识库是权限与检索的隔离单元；系统级角色 `ADMIN`/`MEMBER` 已落地，库级 `KB_ADMIN`/`EDITOR`/`VIEWER` 随本能力引入
- 既有约定：软删 + 唯一约束用**虚拟生成列**（`Account.username_active` 同款方案，MySQL/SQLite 均可）；路由鉴权用 `require_role()`；响应统一 `ApiResponse` 信封

## Goals / Non-Goals

**Goals:**

- 让"用户 → 授权知识库集合"成为可查询的真事实（解锁检索链路）
- 库级授权的最小可用集合：授予 / 改角色 / 移除 / 列举
- 权限语义与既有系统保持一致：软删、审计留痕、错误码复用

**Non-Goals:**

- 不做文档/解析/切分/向量化
- 不做问答端点与引用渲染
- 不做前端界面
- 不做文档级 / 标签级 ACL（项目非目标）

## Decisions

### K1. 授权表用复合主键 + 外键，不引入代理主键

**选择**：`user_kb_grant(user_id, kb_id, role, ...)`，`PRIMARY KEY (user_id, kb_id)`。

**理由**：一个用户在一个库只持一个角色，这是业务事实，用复合主键直接表达，无需额外唯一索引，也天然避免重复授权。

### K2. KB 名称唯一沿用派生列方案

**选择**：`name_active` 虚拟生成列（软删后为 NULL）+ 唯一索引，与 `users.username_active` 完全一致。

**理由**：MySQL 不支持部分索引，已验证方案且测试库 SQLite 也能建表；重复一次已有机制比引入新机制便宜。

### K3. ADMIN 与 KB_ADMIN 的职责边界

**选择**：`ADMIN` 对所有库有完全管理权；`KB_ADMIN` 仅对**自己被授予 KB_ADMIN 的库**有管理权（含成员管理）；`EDITOR` / `VIEWER` 无管理权。

**理由**：两层角色在项目里已定稿；库级管理员必须能管自己的成员，否则每个成员变更都要惊动系统管理员。

### K4. 授权集合查询走仓储而非服务缓存

**选择**：`KbGrantRepository.kb_ids_for_user()` 直查（带 `user_id` 索引），`KbAccessResolver` 默认仍走直查；可选 TTL 缓存保持关闭。

**理由**：`rag-orchestration` 已把缓存设为默认关闭（撤销要零延迟），本 change 只补真实读取实现，不改变该决策。

### K5. 软删知识库同时视为"授权失效"

**选择**：查询授权集合时 JOIN 过滤掉已软删的 KB；KB 软删不物理删授权行（保留审计），但不再出现在任何授权集合里。

**理由**：避免"库已删但仍被检索到"的越权窗口；保留行便于审计与误删恢复。

## Risks / Trade-offs

- **授权集合为空 → 检索返回空**：符合既有语义，但用户体验上"无授权"与"无结果"难以区分 → 后续 QA change 在问答层给出明确提示
- **库级角色校验散落在多个路由**：用依赖函数 `require_kb_role(...)` 统一，避免每个路由重复判断
- **迁移风险**：新增两张表，无存量数据；软删派生列方案已在 `users` 验证过
- **并发重复授予未做 DB 级 upsert**：同一 `(user_id, kb_id)` 并发首次授予时，后到者可能撞复合主键而抛 `IntegrityError`（500）。本期接受该限制（授权变更是低频管理操作，且重试即可）；若后续出现真实冲突，改用 `INSERT ... ON DUPLICATE KEY UPDATE`（MySQL 专有，需方言分支）。**不做半套的 try/except 兜底**——在 READ COMMITTED 下回滚后再查可能仍读不到未提交的冲突行，只会把 500 变成更迷惑的行为
- **软删库残留授权行**：按 K5 保留审计，但暂无清理/对账任务。与 `project.md`「删除一致性：提供对账任务扫孤儿」一致，归后续 ops change

## Migration Plan

1. Alembic 迁移建立 `knowledge_bases` 与 `user_kb_grant`
2. 模型与服务层实现 + 测试
3. 真实 `KbGrantReader` 接线（替代端口的空实现）
4. 无数据迁移（新表）

## Open Questions

- KB 的切分配置（`chunk_*`）以列存储还是 JSON 列？**倾向**：先只存 `embedding_model` / `embed_dim`，切分配置等 ingest change 定稿后再加，避免本 change 猜测字段。

## 实施期决策（签字确认）

1. **授权集合为空的语义**：本 change 只保证"空授权集合 = 检索返回空结果"（沿用 `rag-orchestration` 既有语义）。**不在**检索层增加"无授权 / 无命中"的原因标记，也不新增授权查询端点——区分提示由 **QA change** 在问答响应里给出。
2. **`EDITOR` / `VIEWER` 的写入边界**：本 change 只落角色定义与**授权管理接口自身的校验**（谁能授予/改角色/移除）。"谁能上传文档""谁能提问"这类业务动作校验随 ingest / QA change 补，不预先建权限映射表（YAGNI）。
3. **前端 KB 管理页**：本 change **不做**前端。待后端接口稳定（尤其切分配置定稿）后单独起 change。
4. **`embed_dim` / `embedding_model` 暂不额外校验**：非法值会在 ingest 建 collection 时被真实拒绝；两处规则并存易漂移。若后续接口层需要更早反馈，在 schema（Pydantic）层加一次即可。
5. **`list_kbs` / `list_members` 暂不分页**：一期库与成员规模都很小；待有真实规模（或前端列表需要）时再加，避免过早引入游标/总数约定。
