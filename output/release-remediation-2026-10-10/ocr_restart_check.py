"""Terminate only this test server and its OCR child, then verify durable replay."""
import os,sys,json,time,subprocess,sqlite3,datetime,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'output/release-closure-2026-10-10/recovery';DATA=OUT/'data'
OUT.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(ROOT));os.chdir(ROOT)
os.environ.update(EXPO_DATA_DIR=str(DATA),EXPO_DATABASE_URL='sqlite:///'+str(DATA/'expo.db'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1')
import main,db,auth,httpx,psutil
from jose import jwt
user=db.get_user_by_username('admin')
try:db.create_project('SYNTH-RECOVERY',user)
except ValueError:pass
folders=db.list_folders('SYNTH-RECOVERY');folder=folders[0]['id'] if folders else db.create_folder('SYNTH-RECOVERY','Documents',user)['id']
token=jwt.encode({'sub':str(user['id']),'username':user['username'],'role':user['role'],'ver':user.get('auth_version',0),
    'exp':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)},auth.secret(),algorithm='HS256')
log=open(OUT/'server.log','a',encoding='utf-8');server=None;result={}
def save():(OUT/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
def start():
    child=subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port','8094'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT)
    with httpx.Client(timeout=5) as c:
        for _ in range(100):
            try:
                if c.get('http://127.0.0.1:8094/health/ready').status_code==200:return child
            except Exception:pass
            if child.poll() is not None:raise RuntimeError('Recovery server exited')
            time.sleep(1)
    child.kill();child.wait();raise TimeoutError('Recovery startup timeout')
def document():
    with sqlite3.connect(DATA/'expo.db') as c:
        c.row_factory=sqlite3.Row
        row=c.execute("select filename,path,status,chunks from documents where filename='interrupted-scan.pdf'").fetchone()
        return dict(row) if row else None
try:
    server=start();source=ROOT/'output/release-closure-2026-10-10/sources/scan.pdf'
    with httpx.Client(headers={'Authorization':'Bearer '+token},timeout=60) as c,open(source,'rb') as f:
        r=c.post('http://127.0.0.1:8094/upload',data={'project':'SYNTH-RECOVERY','folder_id':str(folder)},files={'file':('interrupted-scan.pdf',f,'application/pdf')})
        assert r.status_code==200,r.text
    deadline=time.monotonic()+300;ocr=None
    while time.monotonic()<deadline:
        for child in psutil.Process(server.pid).children(recursive=True):
            try:
                if 'services.page_ocr' in child.cmdline():ocr=child;break
            except psutil.NoSuchProcess:pass
        if ocr:break
        time.sleep(.1)
    if not ocr:raise RuntimeError('No real OCR child observed; interruption test not certified')
    result['before_kill']=document();result['first_stage']='OCR';result['ocr_child_observed']=True
    assert result['before_kill']['status'] not in ('ready','ready_with_warnings')
    owned=psutil.Process(server.pid).children(recursive=True)
    server.kill();server.wait(timeout=10)
    for child in owned:
        try:child.kill()
        except psutil.NoSuchProcess:pass
    psutil.wait_procs(owned,timeout=10)
    result['after_kill']=document();save()
    assert result['after_kill']['status'] not in ('ready','ready_with_warnings')
    server=start();deadline=time.monotonic()+900
    while time.monotonic()<deadline:
        with sqlite3.connect(DATA/'ingestion-jobs.sqlite3') as c:
            c.row_factory=sqlite3.Row;job=dict(c.execute('select state,attempts,sha256,error from jobs order by created desc limit 1').fetchone())
        if job['state'] in ('completed','failed'):break
        time.sleep(2)
    result['job']=job;result['after_restart']=document()
    result['source_hash_unchanged']=job['sha256']==hashlib.sha256(source.read_bytes()).hexdigest()==hashlib.sha256(Path(result['after_restart']['path']).read_bytes()).hexdigest()
    with sqlite3.connect(DATA/'expo.db') as c:
        result['integrity']=c.execute('pragma integrity_check').fetchone()[0]
        result['duplicate_documents']=c.execute('select count(*) from documents').fetchone()[0]!=1
    result['pass']=job['state']=='completed' and job['attempts']==2 and result['after_restart']['status']=='ready_with_warnings' and result['source_hash_unchanged'] and not result['duplicate_documents'] and result['integrity']=='ok'
    save();print(json.dumps(result),flush=True)
finally:
    if server and server.poll() is None:
        server.terminate()
        try:server.wait(timeout=15)
        except subprocess.TimeoutExpired:server.kill();server.wait(timeout=10)
    log.close()
