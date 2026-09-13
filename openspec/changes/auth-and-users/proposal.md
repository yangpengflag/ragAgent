## Why

项目定稿要求「多知识库 + 用户权限」，但当前后端只有骨架（无用户实体、无鉴权），前端的刷新重放与 `/login` 跳转也仍是占位。后续每一个业务能力（知识库、文档、问答）都要以「谁在操作、能看哪些库」为前提，因此**账号与认证必须先落地**，否则业务 change 只能建立在匿名请求上，权限模型会被反复返工。

同时，`project.md` 里既定的认证库选型需要修正：`passlib` 最新版（1.7.4）发布于 2020 年、已事实停止维护；`python-jose` 3.3.0 及以下存在算法混淆漏洞（CVE-2024-33663 / CVE-2024-33664）。继续沿用会把安全债写进地基。

## What Changes

- 新增**用户账号**能力：用户实体（用户名、显示名、密码哈希、是否启用、系统角色、公共字段）、由 ADMIN 管理账号（创建 / 列表 / 查看 / 修改显示名与系统角色 / 启用停用 / 重置密码）、密码强度策略、初始管理员引导
- 新增**认证**能力：账号密码登录签发令牌、访问令牌与刷新令牌、令牌刷新、登出与刷新令牌撤销、登录失败限流、以及供路由使用的鉴权依赖（当前用户 / 系统角色校验）
- **修正依赖选型**：`PyJWT`（替代 `python-jose`）+ `pwdlib[argon2]`（Argon2id，替代 `passlib`）
- 前端**接入真实登录态**：登录页、应用启动时的会话引导（用刷新令牌恢复会话）、路由守卫、登出；请求层的「401 刷新重放、刷新失败跳转登录」由占位变为真实行为
- 修订 `openspec/project.md` 的技术栈章节（认证库）与权限模型章节（明确本次只做「系统级角色」，库级 ACL 随知识库能力引入）

**不在本 change 范围内**（避免范围蔓延）：
- 开放注册、邮箱验证、找回密码、第三方登录（LDAP / OAuth2）——仅预留 `AuthProvider` 抽象接口
- 多租户（Tenant）
- **知识库实体本身与库级 ACL**（`KB_ADMIN` / `EDITOR` / `VIEWER` 的授权与检索下推）——留给 `knowledge-base-crud`
- 用户管理界面（本次只交付登录相关 UI；账号管理走 API）
- 密码修改的自助入口（管理员重置即可）

## Capabilities

### New Capabilities

- `identity`：用户账号的实体模型、密码存储与策略、账号管理（ADMIN 视角的增改停用与角色授予）、初始管理员引导
- `authentication`：登录与令牌签发、令牌刷新、登出与撤销、登录失败限流、请求鉴权（当前用户与系统角色依赖）

### Modified Capabilities

- `frontend-shell`：应用外壳从「无鉴权占位」变为「真实登录态」——新增登录页与会话引导、路由守卫按登录态跳转、登出；请求层关于 401 刷新重放与刷新失败跳转登录的需求由占位转为真实行为

## Impact

- **后端新增**：`app/models/user.py`、`app/core/security.py`（哈希与令牌）、`app/services/auth.py`、`app/api/v1/{auth,users}.py`、`app/api/deps.py`（鉴权依赖）、Alembic 迁移（users 表）
- **后端修改**：`app/core/config.py`（`APP_SECRET_KEY`、令牌有效期、Cookie 属性、登录限流阈值、初始管理员配置）、`app/api/v1/__init__.py`（挂载路由）、`.env.example`
- **依赖新增**：`pyjwt`、`pwdlib[argon2]`（`backend/pyproject.toml`）
- **前端新增**：`src/features/auth/{api.ts,hooks,components}`、登录页、`src/app/route-guard`（守卫）、启动会话引导
- **前端修改**：`src/app/routes.tsx`（登录页与守卫接线）、`src/lib/api/session.ts` 的真实刷新实现接线（`setTokenRefresher`）、`AppLayout`（当前用户与登出入口）
- **OpenSpec**：新增 `specs/identity/`、`specs/authentication/`；修改 `specs/frontend-shell/`（delta）；同步修订 `openspec/project.md`
- **环境**：需要 Redis 承载「刷新令牌撤销名单」与「登录失败计数」（本机已有 6379 容器）；需要一个足够强的 `APP_SECRET_KEY`（缺失即启动失败）
- **无破坏性变更**：现有接口（`GET /api/v1/health`）保持匿名可访问，不受鉴权影响
