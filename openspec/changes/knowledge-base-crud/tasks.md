## 1. 数据层（红灯优先）

- [x] 1.1 红灯：写模型测试——`KnowledgeBase` 软删后名称可复用；活跃库名称唯一
- [x] 1.2 绿灯：`KnowledgeBase` 模型（含 `name_active` 派生列 + 唯一索引）+ Alembic 迁移
- [x] 1.3 红灯：写模型测试——同一用户在同一库只持一个角色；软删库不出现在授权集合中（越权排除的断言归 3.1 仓储测试）
- [x] 1.4 绿灯：`UserKbGrant` 模型（复合主键 `user_id + kb_id`，不继承 `BaseModel`：撤销是删行而非软删）+ 迁移。两处实测坑：列类型必须用项目 `GUID`（`sa.Uuid()` 会触发 MySQL error 3780）；downgrade 不可单独 drop 被外键依赖的索引（error 1553）

## 2. 知识与授权服务

- [x] 2.1 红灯：写服务测试——创建/更新/软删 KB，名称冲突返回 409 `conflict`
- [x] 2.2 绿灯：`kb_service`（CRUD + 软删）
- [x] 2.3 红灯：写服务测试——授予/改角色/移除/列成员；重复授予为幂等覆盖；目标不存在或已软删 → 404
- [x] 2.4 绿灯：`kb_grant_service`（成员授权）。实测坑：存在性校验须用 `select` 而非 `Session.get`（后者命中 identity map 会返回已软删实例）

## 3. 真实 KbGrantReader 与接线

- [x] 3.1 红灯：写查询测试——`kb_ids_for_user` 返回该用户全部授权库，且**排除已软删库**（K5）
- [x] 3.2 绿灯：授权集合查询 `kb_grant_service.kb_ids_for_user`（显式排除软删库）+ 端口适配器 `SessionKbGrantReader`（实现 `KbGrantReader`，字符串 UUID 非法时显式报错）
- [x] 3.3 绿灯：接线 `build_kb_access_resolver()`（真实读取、缓存默认关闭）+ 二次鉴权查询 `can_access_kb`

## 4. HTTP 接口

- [ ] 4.1 红灯：写路由测试——KB CRUD 五接口的状态码、响应形状与权限（`ADMIN` 全量、`KB_ADMIN` 本库）
- [ ] 4.2 绿灯：`/api/v1/knowledge-bases` 路由与 `require_kb_role` 依赖
- [ ] 4.3 红灯：写路由测试——成员授权四接口
- [ ] 4.4 绿灯：成员授权路由

## 5. 门禁与收尾

- [ ] 5.1 `uv run pytest` 全绿、`ruff check .` 与 `mypy app` 零错误
- [ ] 5.2 同步 `openspec/specs/knowledge-base/spec.md` 并归档本 change
