"""Add persistent audit for unsuccessful login attempts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_01"
down_revision: str | Sequence[str] | None = "20260728_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=150), nullable=False),
        sa.Column("client_ip", sa.String(length=45), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_login_attempts_username_attempted_at",
        "login_attempts",
        ["username", "attempted_at"],
    )
    op.create_index(
        "ix_login_attempts_client_ip_attempted_at",
        "login_attempts",
        ["client_ip", "attempted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_login_attempts_client_ip_attempted_at", table_name="login_attempts"
    )
    op.drop_index(
        "ix_login_attempts_username_attempted_at", table_name="login_attempts"
    )
    op.drop_table("login_attempts")
