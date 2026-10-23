"""Exercise migrations on disposable databases; never touches the application DB."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DeploymentSchema(unittest.TestCase):
    def test_empty_install_upgrade_data_preservation_and_downgrade(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            env=dict(os.environ,EXPO_DATA_DIR=directory,EXPO_DATABASE_URL='sqlite:///'+str(Path(directory)/'migration.db'))
            code='''
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.autogenerate import compare_metadata
from sqlalchemy import inspect, text
import db
cfg=Config('alembic.ini')
command.upgrade(cfg,'ccc9bcc47ca6')
with db.SessionLocal() as session:
    # Raw SQL: the initial schema predates later ORM user fields (e.g. auth_provider).
    session.execute(text("INSERT INTO users(username,password_hash,role,is_active,auth_version) VALUES ('migration-fixture','synthetic-not-a-login','user',1,0)"))
    session.commit()
command.upgrade(cfg,'b2c3d4e5f6a7')
with db.SessionLocal() as session:
    # The intermediate schema intentionally predates current ORM fields.
    session.execute(text("INSERT INTO projects(name) VALUES ('migration-fixture-project')"))
    project_id=session.execute(text("SELECT id FROM projects WHERE name='migration-fixture-project'")).scalar_one()
    session.add(db.Document(project_id=project_id,filename='synthetic.pdf',path='synthetic.pdf',status='ready'))
    session.commit()
command.upgrade(cfg,'head')
with db.SessionLocal() as session:
    assert session.query(db.User).filter_by(username='migration-fixture').count()==1
    assert session.query(db.Document).filter_by(filename='synthetic.pdf').count()==1
with db.engine.connect() as conn:
    changes=compare_metadata(MigrationContext.configure(conn,opts={'compare_type':True}),db.Base.metadata)
    assert not changes,repr(changes)
    assert conn.exec_driver_sql('PRAGMA foreign_key_check').fetchall()==[]
assert set(db.Base.metadata.tables)<=set(inspect(db.engine).get_table_names())
command.downgrade(cfg,'base')
assert set(inspect(db.engine).get_table_names())<= {'alembic_version'}
print('Migration lifecycle passed')
'''
            result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=45)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
