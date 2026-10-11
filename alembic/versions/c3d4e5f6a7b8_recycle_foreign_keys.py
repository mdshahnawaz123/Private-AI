"""Align recycle references with the existing ORM without changing auth behavior."""
from alembic import op
import sqlalchemy as sa

revision='c3d4e5f6a7b8'
down_revision='b2c3d4e5f6a7'
branch_labels=None
depends_on=None


def upgrade():
    for table in ('documents','projects'):
        foreign_keys=sa.inspect(op.get_bind()).get_foreign_keys(table)
        if any(fk['constrained_columns']==['deleted_by'] and fk['referred_table']=='users'
               and fk['referred_columns']==['id'] for fk in foreign_keys):
            continue
        with op.batch_alter_table(table) as batch:
            batch.create_foreign_key('fk_'+table+'_deleted_by_users','users',['deleted_by'],['id'])


def downgrade():
    for table in ('documents','projects'):
        name='fk_'+table+'_deleted_by_users'
        if any(fk.get('name')==name for fk in sa.inspect(op.get_bind()).get_foreign_keys(table)):
            with op.batch_alter_table(table) as batch:
                batch.drop_constraint(name,type_='foreignkey')
