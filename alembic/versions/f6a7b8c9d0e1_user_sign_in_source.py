"""User sign-in source for company single sign-on (SSO).

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def _has(table, name):
    return name in {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    # db.init_db may already have added these on a running install; keep them.
    if not _has('users', 'auth_provider'):
        op.add_column('users', sa.Column('auth_provider', sa.String(40), nullable=False, server_default='local'))
    if not _has('users', 'external_id'):
        op.add_column('users', sa.Column('external_id', sa.String(255), nullable=True))
        op.create_index('ix_users_external_id', 'users', ['external_id'])


def downgrade():
    with op.batch_alter_table('users') as b:
        if _has('users', 'external_id'):
            try:
                b.drop_index('ix_users_external_id')
            except Exception:
                pass
            b.drop_column('external_id')
        if _has('users', 'auth_provider'):
            b.drop_column('auth_provider')
