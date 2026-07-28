"""Add resume retention metadata and cascade profile deletion."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_01"
down_revision: str | Sequence[str] | None = "20260724_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidate_profiles",
        sa.Column("source_path", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "candidate_profiles",
        sa.Column("resume_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_candidate_profiles_resume_expires_at",
        "candidate_profiles",
        ["resume_expires_at"],
    )
    op.execute(
        """
        UPDATE candidate_profiles
        SET resume_expires_at = created_at + INTERVAL '30 days'
        WHERE cv_text IS NOT NULL
        """
    )
    op.drop_constraint("search_runs_profile_id_fkey", "search_runs", type_="foreignkey")
    op.create_foreign_key(
        "search_runs_profile_id_fkey",
        "search_runs",
        "candidate_profiles",
        ["profile_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("search_runs_profile_id_fkey", "search_runs", type_="foreignkey")
    op.create_foreign_key(
        "search_runs_profile_id_fkey",
        "search_runs",
        "candidate_profiles",
        ["profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_index(
        "ix_candidate_profiles_resume_expires_at",
        table_name="candidate_profiles",
    )
    op.drop_column("candidate_profiles", "resume_expires_at")
    op.drop_column("candidate_profiles", "source_path")
