## Context

`auth_service.refresh()` 的 5 个失败分支都复用登录常量 `_INVALID_CREDENTIALS_MESSAGE = "用户名或密码错误"`：

| 分支 | 位置 |
|---|---|
| 无刷新令牌 | refresh 入口 |
| 签名非法/类型不符 | decode 的 AppError 捕获 |
| `jti` 已被撤销 | 撤销名单命中 |
| 账号不存在或未启用 | 账号查询后 |
| 会话纪元落后 | epoch 校验 |

登录分支（`login()`）使用同一常量是**正确且刻意**的：spec 要求"账号不存在"与"密码错误"对外一致，避免账号枚举。但刷新场景没有"用户名/密码"这一输入，文案必须指代刷新令牌本身。

## Goals / Non-Goals

**Goals:**

- 刷新类失败给出指代正确的可读文案
- 保持 `error_code` / 状态码 / Cookie 清除语义完全不变（客户端零改动）

**Non-Goals:**

- 不新增 `error_code`（`unauthorized` 与 `token_expired` 已够客户端分支）
- 不改登录文案与账号枚举防护
- 不动 503（撤销存储不可用）路径

## Decisions

### D1: 只换文案，不动错误码

**选择**：新增模块级常量 `_INVALID_REFRESH_MESSAGE`，刷新路径全部改用；异常类型仍为 `InvalidCredentialsError`（`401 / unauthorized`）。

**备选**：新增 `InvalidRefreshTokenError` 子类并给新 `error_code`。代价是客户端要跟着改分支，而客户端目前只按 `error_code` 决定是否跳登录——收益为零、破坏面更大。

**理由**：问题出在"文案指代错误"，不是"分类不够细"。

### D2: 文案不透露具体是哪一项校验失败

**选择**：5 个分支共用同一句文案。

**理由**：与登录一致的信息最小化原则——不告诉调用方"是撤销了还是账号停用了"，避免凭据状态探测。诊断细节仍完整落在服务端 `logger.warning` 里（各分支的 reason 不同）。

## Risks / Trade-offs

- **客户端若硬编码了旧文案做展示** → 本次检查：前端按 `error_code` 分支并优先展示后端 `message`，无硬编码；`scripts/e2e_flow.py` 只断言 `error_code`。
- **文案变更属于对外可见变化** → 仅 message，`error_code` 契约不变，风险可控。

## Migration Plan

单文件改动 + 新增测试，无数据迁移、无配置变更。回滚 = 恢复常量引用。

## Open Questions

（无。）
