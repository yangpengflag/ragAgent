"""§4.3 / §4.5 红灯：访问与刷新令牌的四类情形与互不可替代。

对应 design.md D1（无状态访问 + 有状态刷新）、D4（jti）、D14（会话纪元）、
spec 场景「令牌已过期 → 401 token_expired」。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import ErrorCode, TokenExpiredError
from app.core.security import (
    TokenClaimsError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
)

SECRET = "unit-test-secret-key-0123456789abcdef"
ALGORITHM = "HS256"


def _access(
    *, account_id: uuid.UUID | None = None, now: datetime | None = None
) -> str:
    return create_access_token(
        account_id=account_id or uuid.uuid4(),
        system_role="MEMBER",
        secret_key=SECRET,
        algorithm=ALGORITHM,
        expires_min=15,
        now=now,
    )


def _refresh(
    *, account_id: uuid.UUID | None = None, epoch: int = 0, now: datetime | None = None
) -> str:
    return create_refresh_token(
        account_id=account_id or uuid.uuid4(),
        session_epoch=epoch,
        secret_key=SECRET,
        algorithm=ALGORITHM,
        expires_days=7,
        now=now,
    )


def _decode(token: str, token_type: TokenType) -> object:
    return decode_token(
        token=token, expected_type=token_type, secret_key=SECRET, algorithm=ALGORITHM
    )


class TestAccessToken:
    def test_valid_roundtrip_carries_role_and_jti(self) -> None:
        account_id = uuid.uuid4()
        claims = _decode(_access(account_id=account_id), TokenType.ACCESS)
        assert claims.account_id == account_id  # type: ignore[attr-defined]
        assert claims.system_role == "MEMBER"  # type: ignore[attr-defined]
        assert claims.jti  # type: ignore[attr-defined]
        assert claims.session_epoch is None  # type: ignore[attr-defined]

    def test_expired_reports_token_expired(self) -> None:
        """过期必须与"无效"区分：客户端据此走刷新路径（spec 场景）。"""
        past = datetime.now(UTC) - timedelta(minutes=20)
        token = _access(now=past)
        with pytest.raises(TokenExpiredError) as exc_info:
            _decode(token, TokenType.ACCESS)
        assert exc_info.value.error_code == ErrorCode.TOKEN_EXPIRED
        assert exc_info.value.status_code == 401

    def test_tampered_signature_rejected_as_unauthorized(self) -> None:
        token = _access()
        head, body, signature = token.split(".")
        tampered = ("A" if signature[0] != "A" else "B") + signature[1:]
        with pytest.raises(TokenClaimsError) as exc_info:
            _decode(f"{head}.{body}.{tampered}", TokenType.ACCESS)
        assert exc_info.value.error_code == ErrorCode.UNAUTHORIZED

    def test_wrong_secret_rejected_as_unauthorized(self) -> None:
        token = _access()
        with pytest.raises(TokenClaimsError):
            decode_token(
                token=token,
                expected_type=TokenType.ACCESS,
                secret_key=SECRET + "-other",
                algorithm=ALGORITHM,
            )

    @pytest.mark.parametrize("bad", ["", "not-a-jwt", "a.b", "a.b.c", "x.y.z.w"])
    def test_malformed_rejected_as_unauthorized(self, bad: str) -> None:
        with pytest.raises(TokenClaimsError):
            _decode(bad, TokenType.ACCESS)


class TestRefreshToken:
    def test_valid_roundtrip_carries_jti_and_epoch(self) -> None:
        account_id = uuid.uuid4()
        claims = _decode(_refresh(account_id=account_id, epoch=3), TokenType.REFRESH)
        assert claims.account_id == account_id  # type: ignore[attr-defined]
        assert claims.session_epoch == 3  # type: ignore[attr-defined]
        assert claims.jti  # type: ignore[attr-defined]
        assert claims.system_role is None  # type: ignore[attr-defined]

    def test_jti_unique_per_issuance(self) -> None:
        """轮换依赖 jti 唯一：同一账号两次签发不得复用 jti。"""
        first = _decode(_refresh(), TokenType.REFRESH).jti
        second = _decode(_refresh(), TokenType.REFRESH).jti
        assert first != second

    def test_expired_reports_token_expired(self) -> None:
        past = datetime.now(UTC) - timedelta(days=8)
        with pytest.raises(TokenExpiredError):
            _decode(_refresh(now=past), TokenType.REFRESH)

    def test_tampered_signature_rejected(self) -> None:
        token = _refresh()
        head, body, signature = token.split(".")
        tampered = ("A" if signature[0] != "A" else "B") + signature[1:]
        with pytest.raises(TokenClaimsError):
            _decode(f"{head}.{body}.{tampered}", TokenType.REFRESH)

    @pytest.mark.parametrize("bad", ["", "not-a-jwt", "a.b.c"])
    def test_malformed_rejected(self, bad: str) -> None:
        with pytest.raises(TokenClaimsError):
            _decode(bad, TokenType.REFRESH)


class TestTokenTypesAreInterchangeableProof:
    """互不可替代（tasks 4.5 / spec「访问与刷新令牌互相不可替代」）。"""

    def test_access_token_rejected_as_refresh(self) -> None:
        with pytest.raises(TokenClaimsError):
            _decode(_access(), TokenType.REFRESH)

    def test_refresh_token_rejected_as_access(self) -> None:
        with pytest.raises(TokenClaimsError):
            _decode(_refresh(), TokenType.ACCESS)
