"""迁移红线（任务 5.6 / 5.7）。

验证：upgrade 幂等、downgrade 可回退到 base、heads 唯一。

这是集成测试（需要真实 MySQL）。**MySQL 不可用时跳过**，
以保证测试套件在本机中间件未启动的环境下仍然全绿（spec R8）。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import URL, Engine, create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.core.db import build_database_url
from app.models.user import Account

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _test_database_name() -> str:
    """测试库名取自配置，不硬编码（design D9）。"""
    return get_settings().mysql_test_database


def _admin_engine() -> Engine:
    """不带 database 的管理连接（用于 drop/create 测试库）。"""
    settings = get_settings()
    url = URL.create(
        "mysql+pymysql",
        username=settings.mysql_user,
        password=settings.mysql_password or "",
        host=settings.mysql_host,
        port=settings.mysql_port,
    )
    return create_engine(url, pool_pre_ping=True)


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return config


@pytest.fixture(scope="module")
def prepared_test_database() -> Iterator[Config]:
    """准备干净的 ragagent_test 库并指向测试目标。"""
    try:
        engine = _admin_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - 任何连接失败都视为环境不可用
        pytest.skip("MySQL 不可用，跳过迁移集成测试")

    test_database = _test_database_name()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {test_database}"))
        connection.execute(
            text(
                f"CREATE DATABASE {test_database} "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        )

    os.environ["ALEMBIC_TARGET"] = "test"
    config = _alembic_config()
    try:
        yield config
    finally:
        # 后置清理（design D9 / database-conventions：跑完不残留）
        with suppress(Exception):
            command.downgrade(config, "base")
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {test_database}"))
        os.environ.pop("ALEMBIC_TARGET", None)
        engine.dispose()


def _version_rows() -> int:
    settings = get_settings()
    test_database = _test_database_name()
    url = URL.create(
        "mysql+pymysql",
        username=settings.mysql_user,
        password=settings.mysql_password or "",
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=test_database,
    )
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = :db AND table_name = 'alembic_version'"
                ),
                {"db": test_database},
            ).scalar_one()
            if not exists:
                return 0
            return int(
                connection.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar_one()
            )
    finally:
        engine.dispose()


def test_target_resolves_to_test_database():
    """守卫：ALEMBIC_TARGET=test 必须真的落到 *_test 库，防止误伤开发库。

    纯断言、不连库，因此不依赖 `prepared_test_database`（MySQL 不可用时也应能跑）。
    """
    assert build_database_url(test=True).database == _test_database_name()
    assert build_database_url(test=True).database.endswith("_test")


def test_guard_rejects_non_test_database(monkeypatch):
    """守卫本体必须真的拦截：目标库名不以 _test 结尾时拒绝执行迁移。

    不依赖 MySQL —— 守卫在建立连接之前就会抛错。
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "mysql_test_database", "ragagent_dev", raising=False)
    monkeypatch.setenv("ALEMBIC_TARGET", "test")

    with pytest.raises(RuntimeError, match="_test"):
        command.upgrade(_alembic_config(), "head")


def test_heads_is_unique(prepared_test_database):
    script = ScriptDirectory.from_config(prepared_test_database)

    assert len(script.get_heads()) == 1


def test_upgrade_is_idempotent(prepared_test_database):
    config = prepared_test_database

    command.upgrade(config, "head")
    command.upgrade(config, "head")  # 第二次应为无操作

    assert _version_rows() == 1


def test_downgrade_to_base_clears_version(prepared_test_database):
    config = prepared_test_database

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    assert _version_rows() == 0, "downgrade 到 base 后不应残留版本记录"

    command.upgrade(config, "head")  # 复原，便于后续手工验证
    assert _version_rows() == 1


def test_users_table_uniqueness_semantics_on_mysql(prepared_test_database):
    """真实 MySQL 上验证「活跃用户名唯一、软删后让位」。

    这是本变更**唯一无法在 SQLite 上验证**的部分：MySQL 不支持部分索引，
    实现改用「虚拟生成列 + 唯一索引」。若 MySQL 不接受该组合（或生成列未生效），
    这条用例会失败——而不是等到线上才发现"删了账号同名却建不回来"。
    """
    config = prepared_test_database
    command.upgrade(config, "head")

    engine = create_engine(build_database_url(test=True))
    try:
        with engine.connect() as connection:
            generated = connection.execute(
                text(
                    "SELECT extra FROM information_schema.columns "
                    "WHERE table_schema = :db AND table_name = 'users' "
                    "AND column_name = 'username_active'"
                ),
                {"db": _test_database_name()},
            ).scalar_one()
            assert "GENERATED" in generated.upper(), (
                f"username_active 应为生成列，实际: {generated}"
            )

            non_unique = connection.execute(
                text(
                    "SELECT non_unique FROM information_schema.statistics "
                    "WHERE table_schema = :db AND table_name = 'users' "
                    "AND index_name = 'uk_users_username_active'"
                ),
                {"db": _test_database_name()},
            ).scalar_one()
            assert int(non_unique) == 0, "uk_users_username_active 必须是唯一索引"

        with Session(engine) as session:
            session.add(Account(username="dup", display_name="D", password_hash="h"))
            session.commit()

            session.add(Account(username="dup", display_name="Dup II", password_hash="h"))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            survivor = session.execute(select(Account)).scalars().one()
            survivor.soft_delete()
            session.commit()

            session.add(Account(username="dup", display_name="Dup III", password_hash="h"))
            session.commit()  # 软删后同名可重建

            remaining = session.execute(select(Account)).scalars().all()
            assert [row.display_name for row in remaining] == ["Dup III"]
    finally:
        engine.dispose()
