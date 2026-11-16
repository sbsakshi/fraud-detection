"""record model and ladder version on risk scores

Revision ID: a7d3e1f4b2c9
Revises: c190bb280894
Create Date: 2026-10-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d3e1f4b2c9'
down_revision: Union[str, None] = 'c190bb280894'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: rows scored before this migration have no recorded version.
    op.add_column('risk_scores', sa.Column('model_version', sa.String(length=64), nullable=True))
    op.add_column('risk_scores', sa.Column('ladder_version', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('risk_scores', 'ladder_version')
    op.drop_column('risk_scores', 'model_version')
