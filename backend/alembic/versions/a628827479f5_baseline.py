"""baseline

Revision ID: a628827479f5
Revises: 
Create Date: 2026-09-12 22:21:58.025397

**本迁移为空实现，是项目规约「downgrade 不得为空」的唯一例外。**

理由：本 change（project-scaffold）不引入任何业务实体，无表可建；
此迁移仅建立版本基线，使后续 change 的迁移有可回退的起点。
`downgrade()` 为空是合理的——没有对象需要删除。
对应说明见 `openspec/changes/project-scaffold/design.md` 的 Risks 一节。
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'a628827479f5'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
