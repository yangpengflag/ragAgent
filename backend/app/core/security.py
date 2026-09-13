"""认证原语：密码哈希/校验/强度策略 + 访问/刷新令牌签发/解析。

对应 `design.md` D2 / D4 / D8 / D14，tasks.md §4。纯函数、零 I/O：
不触库、不触网络；密钥、算法与有效期等参数由调用方显式传入，
本模块不读 `Settings`——单测无需构造配置，将来的 CLI 复用也不受牵制。

参数收敛约定（§4.7）：算法与有效期在 `Settings`（配置面）；
声明名、令牌类型与密码策略阈值在本模块常量（实现面）。
各只有一处定义，禁止在调用点散写。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from http import HTTPStatus
from typing import Final

import jwt
from pwdlib import PasswordHash

from app.core.exceptions import AppError, ErrorCode, TokenExpiredError

# ---------------------------------------------------------------- 密码策略（design D8）
# 阈值收敛点：改策略只改这里（§4.7）。复杂度字符集要求被 D8 明确否决，勿加。
MIN_PASSWORD_LENGTH: Final = 12
MAX_PASSWORD_LENGTH: Final = 128

_RULE_TOO_SHORT: Final = "password_too_short"
_RULE_TOO_LONG: Final = "password_too_long"
_RULE_SAME_AS_USERNAME: Final = "password_same_as_username"


class PasswordPolicyError(AppError):
    """密码不符合强度策略。

    `details["rule"]` 携带规则标识供调用方条件分支；
    消息与 details 一律不回显密码原文。
    """

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    error_code = ErrorCode.VALIDATION_ERROR


_password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Argon2id 哈希（每次随机加盐，同一密码两次结果不同）。"""
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """常数时间校验；哈希格式非法时返回 False 而不是抛错。"""
    try:
        return _password_hasher.verify(password, password_hash)
    except Exception:  # noqa: BLE001 - 哈希串损坏属"不匹配"，不是服务端错误
        return False


def validate_password_strength(password: str, *, username: str) -> None:
    """校验密码强度；不合规抛 `PasswordPolicyError`（details.rule 指明规则）。

    长度以字符数计；与用户名比较为精确匹配（design D8 字面要求，
    未做大小写折叠——若将来要收紧，先改 spec 再改这里）。
    """
    details: dict[str, str] = {}
    if len(password) < MIN_PASSWORD_LENGTH:
        details["rule"] = _RULE_TOO_SHORT
    elif len(password) > MAX_PASSWORD_LENGTH:
        details["rule"] = _RULE_TOO_LONG
    elif password == username:
        details["rule"] = _RULE_SAME_AS_USERNAME
    if details:
        raise PasswordPolicyError("密码不符合强度策略", details=details)


# ---------------------------------------------------------------- 令牌类型与声明名（§4.7 收敛点）
class TokenType(StrEnum):
    """令牌类型。访问与刷新令牌互不可替代的唯一依据（design D1）。"""

    ACCESS = "access"
    REFRESH = "refresh"


_CLAIM_TYPE: Final = "type"
_CLAIM_ROLE: Final = "role"
_CLAIM_EPOCH: Final = "epoch"


class TokenClaimsError(AppError):
    """令牌无效：签名校验失败、格式非法或与期望类型不符。"""

    status_code = HTTPStatus.UNAUTHORIZED
    error_code = ErrorCode.UNAUTHORIZED


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """解析后的令牌载荷。

    `system_role` 仅访问令牌携带；`session_epoch` 仅刷新令牌携带（design D14）。
    """

    token_type: TokenType
    account_id: uuid.UUID
    jti: str
    issued_at: datetime
    expires_at: datetime
    system_role: str | None
    session_epoch: int | None


def _encode(
    claims: dict[str, object],
    *,
    secret_key: str,
    algorithm: str,
    now: datetime,
    lifetime: timedelta,
) -> str:
    payload: dict[str, object] = {
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + lifetime,
        **claims,
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def _decode(
    token: str,
    *,
    expected_type: TokenType,
    secret_key: str,
    algorithm: str,
) -> dict[str, object]:
    """解码并校验签名/过期/类型；失败抛对应 AppError（401）。

    过期必须与"签名无效/格式非法"区分开（spec：`token_expired` 表示
    客户端可走刷新路径恢复，其余 401 一律要求重新登录）。
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("令牌已过期") from exc
    except jwt.PyJWTError as exc:
        raise TokenClaimsError("令牌无效") from exc

    if payload.get(_CLAIM_TYPE) != expected_type.value:
        # 互不可替代：拿访问令牌当刷新令牌用（或反之）一律拒绝
        raise TokenClaimsError("令牌类型不符")

    missing = [key for key in ("sub", "jti", "iat", "exp") if key not in payload]
    if missing:
        raise TokenClaimsError(f"令牌缺少必需声明: {', '.join(missing)}")
    return payload


def _to_claims(
    payload: dict[str, object],
    token_type: TokenType,
    *,
    system_role_required: bool,
    epoch_required: bool,
) -> TokenClaims:
    try:
        account_id = uuid.UUID(str(payload["sub"]))
    except ValueError as exc:
        # sub 非法但签名有效——仍属"格式非法"，必须 401 而非 500
        raise TokenClaimsError("令牌主体声明非法") from exc
    iat_raw = payload["iat"]
    exp_raw = payload["exp"]
    if not isinstance(iat_raw, int) or not isinstance(exp_raw, int):
        raise TokenClaimsError("令牌时间声明非法")
    issued_at = datetime.fromtimestamp(iat_raw, tz=UTC)
    expires_at = datetime.fromtimestamp(exp_raw, tz=UTC)
    role = payload.get(_CLAIM_ROLE)
    epoch = payload.get(_CLAIM_EPOCH)
    if system_role_required and not isinstance(role, str):
        raise TokenClaimsError("访问令牌缺少角色声明")
    if epoch_required and not isinstance(epoch, int):
        raise TokenClaimsError("刷新令牌缺少会话纪元声明")
    return TokenClaims(
        token_type=token_type,
        account_id=account_id,
        jti=str(payload["jti"]),
        issued_at=issued_at,
        expires_at=expires_at,
        system_role=role if isinstance(role, str) else None,
        session_epoch=epoch if isinstance(epoch, int) else None,
    )


def create_access_token(
    *,
    account_id: uuid.UUID,
    system_role: str,
    secret_key: str,
    algorithm: str,
    expires_min: int,
    now: datetime | None = None,
) -> str:
    """签发访问令牌（无状态，design D1）。

    `now` 仅供测试注入时钟；业务调用方不传。
    """
    issued = now or datetime.now(UTC)
    return _encode(
        {
            "sub": str(account_id),
            _CLAIM_TYPE: TokenType.ACCESS.value,
            _CLAIM_ROLE: system_role,
        },
        secret_key=secret_key,
        algorithm=algorithm,
        now=issued,
        lifetime=timedelta(minutes=expires_min),
    )


def create_refresh_token(
    *,
    account_id: uuid.UUID,
    session_epoch: int,
    secret_key: str,
    algorithm: str,
    expires_days: int,
    now: datetime | None = None,
) -> str:
    """签发刷新令牌（有状态撤销 + 会话纪元，design D4 / D14）。"""
    issued = now or datetime.now(UTC)
    return _encode(
        {
            "sub": str(account_id),
            _CLAIM_TYPE: TokenType.REFRESH.value,
            _CLAIM_EPOCH: session_epoch,
        },
        secret_key=secret_key,
        algorithm=algorithm,
        now=issued,
        lifetime=timedelta(days=expires_days),
    )


def decode_token(
    *,
    token: str,
    expected_type: TokenType,
    secret_key: str,
    algorithm: str,
) -> TokenClaims:
    """解析并校验令牌；类型不符的令牌一律拒绝（互不可替代）。"""
    payload = _decode(
        token, expected_type=expected_type, secret_key=secret_key, algorithm=algorithm
    )
    return _to_claims(
        payload,
        expected_type,
        system_role_required=expected_type is TokenType.ACCESS,
        epoch_required=expected_type is TokenType.REFRESH,
    )
