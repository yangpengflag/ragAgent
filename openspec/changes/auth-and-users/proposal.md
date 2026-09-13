## Why

项目定稿要求「多知识库 + 用户权限」，但当前后端只有骨架（无用户实体、无鉴权）。后续每一个业务能力（知识库、文档、问答）都要以「谁在操作、能看哪些库」为前提，因此**账号与认证必须先落地**，否则业务 change 只能建立在匿名请求上，权限模型会被反复返工。

同时，`project.md` 里既定的认证库选型需要修正：`passlib` 最新版（1.7.4）发布于 2020 年、已事实停止维护；`python-jose` 3.3.0 及以下存在算法混淆漏洞（CVE-2024-33663 / CVE-2024-33664）。继续沿用会把安全债写进地基。

本 change 只交付**后端**身份与认证能力。前端接入（登录页、会话引导、路由守卫、登出）由紧随其后的 `frontend-auth-wiring` 交付——拆开是为了让本 change 的评审集中在一个可独立验证的边界上（接口契约 + 安全语义），而不必同时评审 UI 状态机。

## What Changes

- 新增**用户账号**能力：用户实体（用户名、显示名、密码哈希、是否启用、系统角色、公共字段）、由 ADMIN 管理账号（创建 / 列表 / 查看 / 修改显示名与系统角色 / 启用停用 / 删除 / 重置密码）、密码强度策略、初始管理员引导
- 新增**认证**能力：账号密码登录签发令牌、访问令牌与刷新令牌（刷新令牌走 `HttpOnly` Cookie）、令牌刷新与轮换、登出与刷新令牌撤销、登录失败限流、以及供路由复用的鉴权依赖（当前账号 / 系统角色校验）
- **修正依赖选型**：`PyJWT`（替代 `python-jose`）+ `pwdlib[argon2]`（Argon2id，替代 `passlib`）
- 修订 `openspec/project.md` 的技术栈章节（认证库）与权限模型章节（明确本次只做「系统级角色」，库级 ACL 随知识库能力引入）

**不在本 change 范围内**：
- 开放注册、邮箱验证、找回密码、第三方登录（LDAP / OAuth2）——仅预留 `AuthProvider` 抽象接口
- 多租户（Tenant）
- **知识库实体本身与库级 ACL**（`KB_ADMIN` / `EDITOR` / `VIEWER` 的授权与检索下推）——留给 `knowledge-base-crud`
- **一切前端改动**（登录页、会话引导、守卫、登出）——留给 `frontend-auth-wiring`
- 密码自助修改（管理员重置即可）

## Capabilities

### New Capabilities

- `identity`：用户账号的实体模型、密码存储与策略、账号管理（ADMIN 视角的增改停用与角色授予）、初始管理员引导
- `authentication`：登录与令牌签发、令牌刷新与轮换、登出与撤销、登录失败限流、请求鉴权（当前账号与系统角色依赖）

### Modified Capabilities

（无。本 change 只新增后端能力，不改动任何既有能力的对外行为——`GET /api/v1/health` 保持匿名可访问。）

## Impact

- **后端新增**：`app/models/user.py`、`app/core/security.py`（哈希与令牌）、`app/services/auth.py`、`app/api/v1/{auth,users}.py`、`app/api/deps.py`（鉴权依赖）、Alembic 迁移（users 表）
- **后端修改**：`app/core/config.py`（签名密钥、令牌有效期、Cookie 属性、登录限流阈值、初始管理员配置）、`app/api/v1/__init__.py`（挂载路由）、`app/main.py`（启动引导接线）、`.env.example`
- **依赖新增**：`pyjwt`、`pwdlib[argon2]`（`backend/pyproject.toml`）
- **前端**：本 change **不改动**前端；`frontend-shell` 里注入式的刷新占位（`setTokenRefresher`）保持原状，直到 `frontend-auth-wiring` 接线
- **OpenSpec**：新增 `specs/identity/`、`specs/authentication/`；同步修订 `openspec/project.md`
- **环境**：需要 Redis 承载「刷新令牌撤销名单」与「登录失败计数」（本机已有 6379 容器）；需要一个足够强的 `APP_SECRET_KEY`（缺失即启动失败）
- **无破坏性变更**：既有接口（`GET /api/v1/health`）保持匿名可访问，不受鉴权影响
