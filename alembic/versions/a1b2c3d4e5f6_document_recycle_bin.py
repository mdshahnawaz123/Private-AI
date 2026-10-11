"""add documents.deleted_at / deleted_by for the recycle-bin feature

Revision ID: a1b2c3d4e5f6
Revises: ccc9bcc47ca6
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = 'ccc9bcc47ca6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('documents') as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('deleted_by', sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table('documents') as batch_op:
        batch_op.drop_column('deleted_by')
        batch_op.drop_column('deleted_at')
