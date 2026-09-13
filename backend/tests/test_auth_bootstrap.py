"""§5 红灯：初始管理员引导（tasks 5.17–5.18，design D10）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import PasswordPolicyError
from app.models.user import Account
from app.services.auth_service import bootstrap_admin


def _count_accounts(session: Session) -> int:
    return len(session.execute(select(Account)).scalars().all())


class TestBootstrapAdmin:
    def test_creates_admin_when_table_empty(self, sqlite_session: Session, capsys) -> None:
        status = bootstrap_admin(
            sqlite_session, username="root-admin", password="root-admin-pass-1"
        )
        assert status == "created"
        admin = sqlite_session.execute(select(Account)).scalars().one()
        assert admin.system_role == "ADMIN"
        assert admin.username == "root-admin"
        # 日志不含密码
        assert "root-admin-pass-1" not in capsys.readouterr().out

    def test_skips_when_table_not_empty(self, sqlite_session: Session) -> None:
        sqlite_session.add(
            Account(username="existing", display_name="E", password_hash="x")
        )
        sqlite_session.commit()

        status = bootstrap_admin(
            sqlite_session, username="root-admin", password="root-admin-pass-1"
        )
        assert status == "table_not_empty"
        assert _count_accounts(sqlite_session) == 1

    def test_skips_when_not_configured(self, sqlite_session: Session) -> None:
        status = bootstrap_admin(sqlite_session, username=None, password=None)
        assert status == "not_configured"
        assert _count_accounts(sqlite_session) == 0

    def test_duplicate_username_treated_as_exists(
        self, sqlite_session: Session, monkeypatch
    ) -> None:
        """并发/重复启动撞唯一约束时不得启动失败（5.17）。"""
        original_commit = sqlite_session.commit

        def racing_commit() -> None:
            # 模拟另一实例在检查与提交之间已插入同名账号
            monkeypatch.setattr(sqlite_session, "commit", original_commit)
            raise IntegrityError("duplicate", None, Exception("uk conflict"))

        monkeypatch.setattr(sqlite_session, "commit", racing_commit)
        status = bootstrap_admin(
            sqlite_session, username="root-admin", password="root-admin-pass-1"
        )
        assert status == "exists"

    def test_repeated_startup_is_idempotent(self, sqlite_session: Session) -> None:
        """重复调用第二次走 table_not_empty，而非报唯一约束冲突。"""
        assert (
            bootstrap_admin(
                sqlite_session, username="root-admin", password="root-admin-pass-1"
            )
            == "created"
        )
        assert (
            bootstrap_admin(
                sqlite_session, username="root-admin", password="root-admin-pass-1"
            )
            == "table_not_empty"
        )

    def test_weak_bootstrap_password_rejected(self, sqlite_session: Session) -> None:
        """引导密码同样受强度策略约束（design D8 对所有密码生效）。"""
        with pytest.raises(PasswordPolicyError):
            bootstrap_admin(sqlite_session, username="root-admin", password="short")
