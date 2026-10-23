"""Persist the project description field.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def _has(table, name):
    return name in {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    # Some local installs already added these through db.init_db; preserve them.
    if not _has('projects', 'description'):
        op.add_column('projects', sa.Column('description', sa.Text(), nullable=True))


def downgrade():
    if _has('projects', 'description'):
        op.drop_column('projects', 'description')
