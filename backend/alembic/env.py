"""Alembic 环境配置。

数据库 URL 由应用配置拼装（不写死在 alembic.ini）；
设 `ALEMBIC_TARGET=test` 可切到测试库 `MYSQL_TEST_DATABASE`。
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# 让 alembic 能 import app.*（把 backend/ 加入 sys.path）
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.db import build_database_url  # noqa: E402
from app.models.base import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    use_test = os.getenv("ALEMBIC_TARGET", "").lower() == "test"
    url = build_database_url(test=use_test)
    # 守卫：声明作用于测试库时，目标库名必须以 _test 结尾，防止误伤开发库
    if use_test and not (url.database or "").endswith("_test"):
        raise RuntimeError(
            f"ALEMBIC_TARGET=test 但解析出的目标库为 '{url.database}'，"
            "不以 _test 结尾，拒绝执行迁移"
        )
    return url.render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {}) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
