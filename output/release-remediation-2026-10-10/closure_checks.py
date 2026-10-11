"""Synthetic-only closure evidence; never points at production storage."""
import os,sys,json,time,datetime,subprocess,threading,sqlite3,hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/release-closure-2026-10-10';DATA=OUT/'data';SOURCES=OUT/'sources'
for p in (OUT,DATA,SOURCES):p.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
os.environ.update(EXPO_DATA_DIR=str(DATA),EXPO_DATABASE_URL='sqlite:///'+str(DATA/'expo.db'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1')
import httpx,psutil,fitz
from reportlab.pdfgen import canvas

def save(name,value):(OUT/name).write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')

specs=[('pump-spec.pdf','PMP-483','pressure','685','kPa','Draft'),
       ('ventilation.pdf','AHU-926','pressure','315','Pa','Proposed'),
       ('duct-detail.pdf','DCT-572','width','640','mm','Pending'),
       ('pipe-register.pdf','PIP-384','diameter','125','mm','Existing'),
       ('tank-note.pdf','TNK-719','height','8','m','TBC'),
       ('wall-detail.pdf','WAL-628','thickness','225','mm','Draft')]
def generate():
    for name,tag,prop,value,unit,status in specs:
        path=SOURCES/name;c=canvas.Canvas(str(path),pagesize=(595,842))
        lines=['SYNTHETIC ENGINEERING TEST - NOT FOR CONSTRUCTION','Project code: SYNTH-CLOSURE.',
               f'Revision C. Status: {status}.',f'Equipment tag: {tag}.',
               f'The {prop} for {tag} is {value} {unit}.',
               'Values remain subject to independent engineering review.']
        c.setFont('Helvetica',12)
        for i,line in enumerate(lines):c.drawString(35,790-35*i,line)
        c.save()
        with fitz.open(path) as d:d[0].get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(str(path)+'.png')
    with fitz.open() as d:
        p=d.new_page(width=595,height=842);p.insert_image(p.rect,filename=str(SOURCES/specs[0][0])+'.png');d.save(SOURCES/'scan.pdf')
    save('expected.json',[dict(zip(('file','tag','property','value','unit','status'),s)) for s in specs])

if '--generate' in sys.argv:
    generate();print('Generated 7 synthetic PDFs');raise SystemExit

import main,db,auth
from jose import jwt
user=db.get_user_by_username('admin')
try:db.create_project('SYNTH-CLOSURE',user)
except ValueError:pass
folders=db.list_folders('SYNTH-CLOSURE')
folder=folders[0]['id'] if folders else db.create_folder('SYNTH-CLOSURE','Documents',user)['id']
token=jwt.encode({'sub':str(user['id']),'username':user['username'],'role':user['role'],'ver':user.get('auth_version',0),
                 'exp':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=3)},auth.secret(),algorithm='HS256')
log=open(OUT/'server.log','w',encoding='utf-8')
server=subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port','8093'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT)
headers={'Authorization':'Bearer '+token};stop=threading.Event();resources=[]
def client():return httpx.Client(base_url='http://127.0.0.1:8093',headers=headers,timeout=180)
def queues():
    try:
        with sqlite3.connect(DATA/'ingestion-jobs.sqlite3',timeout=2) as c:return dict(c.execute('select state,count(*) from jobs group by state'))
    except Exception:return {}
def monitor():
    while not stop.wait(2):
        try:
            procs=[psutil.Process(server.pid)]+psutil.Process(server.pid).children(recursive=True)
            row={'time':time.time(),'cpu_percent':psutil.cpu_percent(),'available_ram':psutil.virtual_memory().available,
                 'rss':sum(p.memory_info().rss for p in procs),'queue':queues(),'disk_free':psutil.disk_usage(str(OUT)).free}
            io=psutil.disk_io_counters();row['host_disk_read_bytes']=io.read_bytes;row['host_disk_write_bytes']=io.write_bytes
            start=time.monotonic()
            with sqlite3.connect(DATA/'expo.db',timeout=2) as c:c.execute('BEGIN IMMEDIATE');c.rollback()
            row['db_write_lock_probe_seconds']=time.monotonic()-start
            try:
                gpu=subprocess.run(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5)
                row['gpu']=gpu.stdout.strip()
            except Exception:pass
            resources.append(row);save('resources.json',resources)
        except Exception as exc:resources.append({'time':time.time(),'probe_error':str(exc)})
def wait_jobs(seconds=1200):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        q=queues()
        if q and not any(q.get(s,0) for s in ('queued','running','retry')):return q
        time.sleep(2)
    raise TimeoutError('Synthetic ingestion queue did not drain')
def upload(pair):
    path,name=pair;start=time.monotonic()
    with client() as c,open(path,'rb') as f:r=c.post('/upload',data={'project':'SYNTH-CLOSURE','folder_id':str(folder)},files={'file':(name,f,'application/pdf')})
    return {'file':name,'http':r.status_code,'seconds':time.monotonic()-start,'response':r.json()}
def ask(question,focus):
    with client() as c:
        start=time.monotonic();r=c.post('/ask_stream',json={'project':'SYNTH-CLOSURE','focus_doc':'Documents/'+focus,'query':question,'messages':[],'k':8})
    events=[json.loads(l[6:]) for l in r.text.splitlines() if l.startswith('data: ')]
    return {'question':question,'focus':focus,'http':r.status_code,'seconds':time.monotonic()-start,
            'answer':''.join(e.get('text','') for e in events if e.get('type')=='token'),'events':events}
try:
    with client() as c:
        for _ in range(100):
            try:
                if c.get('/health/ready').status_code==200:break
            except Exception:pass
            if server.poll() is not None:raise RuntimeError('Synthetic server exited')
            time.sleep(1)
        else:raise RuntimeError('Synthetic server startup timed out')
    threading.Thread(target=monitor,daemon=True).start()
    with ThreadPoolExecutor(max_workers=4) as pool:
        uploads=list(pool.map(upload,[(SOURCES/s[0],s[0]) for s in specs]))
    save('native-uploads.json',uploads);save('native-queue.json',wait_jobs());print('Native uploads complete',flush=True)
    answers=[]
    for name,tag,prop,value,unit,status in specs:
        for question in (f'What {prop} is specified for {tag}?',f'Give the documented {prop} for equipment {tag}.'):
            record=ask(question,name);record['expected']={'value':value,'unit':unit,'file':name,'page':1}
            record['pass']=f'{value} {unit}' in record['answer'] and f'[SOURCE: {name} | PAGE 1]' in record['answer']
            answers.append(record);save('answers.json',answers);print(json.dumps({'question':question,'pass':record['pass']}),flush=True)
    with sqlite3.connect(DATA/'expo.db') as c:before=c.execute('select count(*) from documents').fetchone()[0]
    repeated=upload((SOURCES/specs[0][0],specs[0][0]));wait_jobs()
    with sqlite3.connect(DATA/'expo.db') as c:after=c.execute('select count(*) from documents').fetchone()[0]
    save('reupload.json',{'before':before,'after':after,'pass':before==after,'response':repeated});print('Repeat upload checked',flush=True)
    for concurrency in (4,8):
        start=time.monotonic()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            uploads=list(pool.map(upload,[(SOURCES/'scan.pdf',f'scan-{concurrency}-{i}.pdf') for i in range(concurrency)]))
        q=wait_jobs();states=[]
        with sqlite3.connect(DATA/'expo.db') as c:
            rows=c.execute('select filename,path,status from documents where filename like ?',(f'scan-{concurrency}-%',)).fetchall()
        for name,path,status in rows:
            meta=json.loads(Path(path+'.index.json').read_text()) if Path(path+'.index.json').exists() else {}
            states.append({'file':name,'status':status,'pages':[{'ocr':p.get('page_ocr_status'),'verification':p.get('verification_state')} for p in meta.get('pages',[])]})
        save(f'scan-load-{concurrency}.json',{'concurrency':concurrency,'seconds':time.monotonic()-start,'uploads':uploads,'queue':q,'states':states})
        print(f'Scan batch {concurrency} complete',flush=True)
        if any(s['status'] not in ('ready_with_warnings','review_required') for s in states):break
    with sqlite3.connect(DATA/'expo.db') as c:
        integrity={'integrity':c.execute('pragma integrity_check').fetchone()[0],'foreign_keys':c.execute('pragma foreign_key_check').fetchall(),
                   'duplicate_document_rows':c.execute('select filename,count(*) from documents where deleted_at is null group by project_id,folder_id,filename,path having count(*)>1').fetchall()}
    save('integrity.json',integrity)
finally:
    stop.set();server.terminate()
    try:server.wait(timeout=20)
    except subprocess.TimeoutExpired:server.kill();server.wait(timeout=10)
    log.close();save('resources.json',resources)
