"""§4.1 红灯：密码哈希与强度策略。

对应 design.md D2（pwdlib[argon2]）与 D8（长度 12–128、不得与用户名相同）。
原语为纯函数、零 I/O；策略失败以**规则标识**报错且不回显密码值。
"""

from __future__ import annotations

import pytest

from app.core.exceptions import ErrorCode
from app.core.security import (
    PasswordPolicyError,
    hash_password,
    validate_password_strength,
    verify_password,
)

# 12–128 边界内且不等于用户名的通用密码
_VALID = "correct-horse-battery-42"


class TestHashAndVerify:
    def test_same_password_hashes_differently(self) -> None:
        """Argon2id 每次随机加盐：同一密码两次哈希互不相同。"""
        assert hash_password(_VALID) != hash_password(_VALID)

    def test_verify_correct_password(self) -> None:
        assert verify_password(_VALID, hash_password(_VALID)) is True

    def test_verify_wrong_password(self) -> None:
        assert verify_password("wrong-password-1234", hash_password(_VALID)) is False

    def test_hash_is_argon2id(self) -> None:
        """锁定算法选型（design D2）：必须是 Argon2id，而不是库里"碰巧推荐"的其他算法。"""
        assert hash_password(_VALID).startswith("$argon2id$")


class TestPasswordStrength:
    """强度策略（design D8）：失败抛 PasswordPolicyError，details.rule 为规则标识。"""

    @pytest.mark.parametrize(
        ("rule", "password"),
        [
            ("password_too_short", "a" * 11),
            ("password_too_long", "a" * 129),
        ],
    )
    def test_length_boundaries_rejected_with_rule_id(
        self, rule: str, password: str
    ) -> None:
        with pytest.raises(PasswordPolicyError) as exc_info:
            validate_password_strength(password, username="alice")
        assert exc_info.value.details is not None
        assert exc_info.value.details["rule"] == rule
        assert exc_info.value.error_code == ErrorCode.VALIDATION_ERROR

    def test_same_as_username_rejected_with_rule_id(self) -> None:
        """用户名本身满足长度要求时也不得作为密码。"""
        with pytest.raises(PasswordPolicyError) as exc_info:
            validate_password_strength("alice-the-admin", username="alice-the-admin")
        assert exc_info.value.details is not None
        assert exc_info.value.details["rule"] == "password_same_as_username"

    @pytest.mark.parametrize("password", ["a" * 12, "a" * 128])
    def test_boundary_lengths_accepted(self, password: str) -> None:
        # 不抛即通过
        validate_password_strength(password, username="bob")

    def test_error_message_does_not_echo_password(self) -> None:
        """异常文本与 details 都不得包含密码原文（防日志泄漏）。"""
        secret = "leak-123"  # 8 位，必然触发 too_short
        with pytest.raises(PasswordPolicyError) as exc_info:
            validate_password_strength(secret, username="alice")
        assert secret not in str(exc_info.value)
        assert secret not in str(exc_info.value.details)
