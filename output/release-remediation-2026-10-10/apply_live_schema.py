"""Backed-up live schema maintenance; run only while the app is stopped."""
import os,sys,sqlite3,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];os.chdir(ROOT);sys.path.insert(0,str(ROOT))
OUT=ROOT/'output/remaining-release-checks-2026-10-10/live-migration';OUT.mkdir(parents=True,exist_ok=True)
target=ROOT/'data/expo.db'
def fingerprint(connection,table):
    rows=connection.execute('select * from '+table+' order by id').fetchall()
    return hashlib.sha256(json.dumps(rows,default=str).encode()).hexdigest(),len(rows)
with sqlite3.connect(target) as c:
    before={table:fingerprint(c,table) for table in ('users','projects','documents')}
    with sqlite3.connect(OUT/'before.db') as backup:c.backup(backup)
    assert c.execute('pragma integrity_check').fetchone()[0]=='ok'
    assert not c.execute('pragma foreign_key_check').fetchall()
from alembic import command
from alembic.config import Config
command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
with sqlite3.connect(target) as c:
    after={table:fingerprint(c,table) for table in before}
    result={'version':c.execute('select version_num from alembic_version').fetchone()[0],
        'integrity':c.execute('pragma integrity_check').fetchone()[0],
        'foreign_key_violations':len(c.execute('pragma foreign_key_check').fetchall()),
        'preserved':before==after,'row_counts':{k:v[1] for k,v in after.items()}}
    assert before==after,'Account/project/document data changed unexpectedly'
    assert result['integrity']=='ok' and not result['foreign_key_violations']
(OUT/'result.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
