# Proposal: knowledge-base-crud

## Why

`rag-orchestration-langchain` 把检索链路搭好了，但**授权数据没有真数据源**：`KbAccessResolver` 面向 `KbGrantReader` 端口编程，真实实现缺失，检索只能用假授权跑。同时 `project.md` 把知识库定为"权限与检索的隔离单元"，而目前没有知识库实体、没有库级角色、没有授权表——后续的文档入库与问答都无从附着。

本 change 交付知识库与授权的数据与接口层，让"用户 → 授权知识库集合"成为可查询的真实事实，为 ingest（文档/向量化）与 QA（问答）铺路。

## What Changes

- **知识库实体**：`KnowledgeBase`（名称唯一、软删；承载 `embedding_model` / `embed_dim` 与切分配置），Alembic 迁移
- **库级授权**：`user_kb_grant(user_id, kb_id, role)`，`role ∈ {KB_ADMIN, EDITOR, VIEWER}`；同一用户在同一库只持一个角色
- **CRUD 接口**：创建 / 列表 / 详情 / 更新 / 软删；`ADMIN` 可管全部，`KB_ADMIN` 可管本库
- **成员授权接口**：授予 / 改角色 / 移除 / 列出成员（限 `ADMIN` 或本库 `KB_ADMIN`）
- **真实 `KbGrantReader`**：MySQL 仓储实现，接线到 `KbAccessResolver`，使检索阶段的授权过滤拿到真数据
- **二次鉴权支撑**：提供"某用户是否可访问某知识库 / 某批 chunk 所属库是否全部授权"的查询能力，供后续问答端点在返回引用前复核

## Capabilities

### New Capabilities

- `knowledge-base`: 知识库实体与库级授权（成员、角色、授权集合查询），以及检索阶段授权数据的真数据源

### Modified Capabilities

（无）

## Impact

- **代码**：`app/models/`（KB 与授权表）、`app/api/v1/`（新增路由）、`app/services/`（KB 与授权服务）、`app/schemas/`、`alembic/versions/`
- **依赖**：无新增
- **兼容性**：`user_kb_grant` 为空时，非 `ADMIN` 用户的授权集合为空 → 检索返回空结果（与既有"空授权短路"语义一致）
- **非目标**：文档上传与解析、切分、向量化（ingest change）；问答端点与引用渲染（QA change）；前端界面
