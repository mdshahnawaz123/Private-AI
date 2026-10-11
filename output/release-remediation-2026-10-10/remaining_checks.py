"""Isolated real pipeline checks. Never points the test server at production data."""
import os,sys,json,time,subprocess,sqlite3,datetime,threading,statistics
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output'/os.environ.get('RELEASE_CHECK_OUTPUT','remaining-release-checks-2026-10-10')
DATA=OUT/'data'; SOURCES=OUT/'sources'
for p in (OUT,DATA,SOURCES,OUT/'tmp'):p.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
os.environ.update(EXPO_DATA_DIR=str(DATA),EXPO_DATABASE_URL='sqlite:///'+str(DATA/'expo.db'),EXPO_PORT='8092',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1')
import tempfile
tempfile.tempdir=str(OUT/'tmp')
os.environ['TMP']=os.environ['TEMP']=str(OUT/'tmp')
import fitz,httpx,psutil
from reportlab.pdfgen import canvas
from jose import jwt

def save(name,data):
    (OUT/name).write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')

def generate(name,project,area,approved='Draft'):
    p=SOURCES/name;c=canvas.Canvas(str(p),pagesize=(595,842))
    c.setFont('Helvetica',14)
    lines=[f'SYNTHETIC TEST DOCUMENT - {project}',f'Drawing number SYNTH-060. Revision B. Status: {approved}.',
           f'Project code: {project}. Equipment tag: AHU-017.',
           'Room Alpha has a clear width of 4 m and clear length of 6 m.',
           'The design pressure for equipment AHU-017 is 250 Pa.',
           'This synthetic source does not constitute construction approval.']
    for i,line in enumerate(lines):c.drawString(35,790-i*30,line)
    c.setFont('Helvetica',12)
    xs=[35,270,430];ys=[555,525,495]
    for y in [570,540,510,480]:c.line(35,y,550,y)
    for x in [35,255,415,550]:c.line(x,480,x,570)
    for y,row in zip(ys,[['Metric','SQ.M.','Qualification'],['Plot Area',str(area),approved],['GFA Allowed','500.00','Limit']]):
        for x,text in zip(xs,row):c.drawString(x,y,text)
    c.save()
    with fitz.open(p) as doc:
        doc[0].get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(str(p)+'.png')
    return p

def setup():
    import main,db
    user=db.get_user_by_username('admin')
    folders={}
    for name in ('SYNTH-A','SYNTH-B'):
        try:db.create_project(name,user)
        except ValueError:pass
        fs=db.list_folders(name)
        folders[name]=fs[0]['id'] if fs else db.create_folder(name,'Documents',user)['id']
    save('setup.json',{'folders':folders})
    return user,folders

if __name__=='__main__':
    a=generate('native-a.pdf','SYNTH-A',123.45)
    b=generate('native-b.pdf','SYNTH-B',987.65,'Proposed')
    scan=SOURCES/'scan.pdf'
    with fitz.open() as doc:
        page=doc.new_page(width=595,height=842);page.insert_image(page.rect,filename=str(a)+'.png');doc.save(scan)
    generate('revision-new.pdf','SYNTH-A',222.22,'Pending')
    user,folders=setup()
    import auth
    token=jwt.encode({'sub':str(user['id']),'username':user['username'],'role':user['role'],'ver':user.get('auth_version',0),
        'exp':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=4)},auth.secret(),algorithm='HS256')
    log=open(OUT/'server.log','w',encoding='utf-8')
    server=subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port','8092'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT)
    stats=[];stop=threading.Event()
    def monitor():
        while not stop.wait(1):
            try:
                proc=psutil.Process(server.pid);processes=[proc]+proc.children(recursive=True)
                stats.append({'time':time.time(),'rss':sum(p.memory_info().rss for p in processes if p.is_running()),
                    'system_cpu_percent':psutil.cpu_percent(),'system_available_ram':psutil.virtual_memory().available,
                    'disk_free':psutil.disk_usage(str(OUT)).free,
                    'process_cpu_seconds':sum(sum(p.cpu_times()[:2]) for p in processes if p.is_running()),
                    'queue':queue_status()})
            except Exception:pass
    def queue_status():
        try:
            with sqlite3.connect(DATA/'ingestion-jobs.sqlite3',timeout=1) as c:return dict(c.execute('select state,count(*) from jobs group by state').fetchall())
        except Exception:return {}
    headers={'Authorization':'Bearer '+token};base='http://127.0.0.1:8092'
    def client():return httpx.Client(base_url=base,headers=headers,timeout=180)
    def upload(project,path,name=None):
        started=time.monotonic()
        with client() as c,open(path,'rb') as f:r=c.post('/upload',data={'project':project,'folder_id':str(folders[project])},files={'file':(name or path.name,f,'application/pdf')})
        return {'project':project,'filename':name or path.name,'http':r.status_code,'seconds':time.monotonic()-started,'response':r.json()}
    def documents():
        with sqlite3.connect(DATA/'expo.db') as c:
            c.row_factory=sqlite3.Row
            return [dict(r) for r in c.execute('select p.name project,d.filename,d.path,d.status,d.chunks from documents d join projects p on d.project_id=p.id')]
    def wait_jobs(limit=600):
        start=time.monotonic()
        while time.monotonic()-start<limit:
            q=queue_status()
            if q and not any(q.get(k,0) for k in ('queued','running','retry')):return True
            time.sleep(2)
        return False
    def ask(project,query,focus=None):
        start=time.monotonic()
        try:
            payload={'project':project,'query':query,'messages':[],'k':8}
            if focus is not None:payload['focus_doc']=focus
            with client() as c:r=c.post('/ask_stream',json=payload)
            events=[json.loads(l[6:]) for l in r.text.splitlines() if l.startswith('data: ')]
            return {'project':project,'query':query,'http':r.status_code,'seconds':time.monotonic()-start,
                'answer':''.join(e.get('text','') for e in events if e.get('type')=='token'),'events':events}
        except Exception as e:return {'project':project,'query':query,'seconds':time.monotonic()-start,'error':repr(e)}
    try:
        for _ in range(90):
            try:
                if httpx.get(base+'/health/ready',timeout=2).status_code==200:break
            except Exception:pass
            if server.poll() is not None:raise RuntimeError('Isolated test server exited')
            time.sleep(1)
        else:raise RuntimeError('Isolated server did not become ready')
        threading.Thread(target=monitor,daemon=True).start()
        with ThreadPoolExecutor(max_workers=4) as ex:
            intake=list(ex.map(lambda v:upload(*v),[('SYNTH-A',a),('SYNTH-B',b),('SYNTH-A',a,'native-copy.pdf'),('SYNTH-A',scan)]))
        save('uploads.json',intake);print('UPLOADS '+json.dumps(intake),flush=True)
        drained=wait_jobs();save('ingestion.json',{'drained':drained,'queue':queue_status(),'documents':documents()})
        print('INGESTION '+json.dumps({'drained':drained,'queue':queue_status(),'documents':documents()}),flush=True)
        cases=[('SYNTH-A','What is the Plot Area?','Documents/native-a.pdf'),('SYNTH-B','What is the Plot Area?','Documents/native-b.pdf'),
            ('SYNTH-A','What is the design pressure for equipment AHU-017?','Documents/native-a.pdf'),
            ('SYNTH-A','Is revision B approved for construction?','Documents/native-a.pdf'),
            ('SYNTH-A','What is the equipment tag and drawing number?','Documents/scan.pdf'),
            ('SYNTH-A','What is the Plot Area of project SYNTH-B?',None),
            ('SYNTH-A','What is the design pressure for equipment SYNTH-061?','Documents/native-a.pdf')]
        qa=[]
        for case in cases:
            answer=ask(*case);qa.append(answer);save('answers.json',qa);print('ANSWER '+json.dumps(answer,ensure_ascii=False),flush=True)
        loads=[]
        for n in (4,8,16,32,64):
            start=time.monotonic()
            with ThreadPoolExecutor(max_workers=n) as ex:answers=list(ex.map(lambda _:ask('SYNTH-A','What is the Plot Area?','Documents/native-a.pdf'),range(n)))
            lat=sorted(a['seconds'] for a in answers)
            row={'concurrency':n,'scope':'HTTP deterministic source-table answer','requests':n,'wall_seconds':time.monotonic()-start,
                'p50_seconds':statistics.median(lat),'p95_seconds':lat[min(len(lat)-1,int(len(lat)*.95))],
                'correct':sum(a.get('http')==200 and '123.45' in a.get('answer','') and '987.65' not in a.get('answer','') for a in answers),'answers':answers}
            loads.append(row);save('http-load.json',loads);print('LOAD '+json.dumps({k:v for k,v in row.items() if k!='answers'}),flush=True)
        # Actual retrieval/reranking/model workload: stop scaling on saturation.
        models=[]
        for n in (4,8,16,32,64):
            with ThreadPoolExecutor(max_workers=n) as ex:answers=list(ex.map(lambda _:ask('SYNTH-A','What design pressure is specified for AHU-017?','Documents/native-a.pdf'),range(n)))
            row={'concurrency':n,'answers':answers,'max_seconds':max(a['seconds'] for a in answers),'errors':sum('error' in a or a.get('http')!=200 for a in answers)}
            models.append(row);save('model-load.json',models);print('MODEL '+json.dumps({k:v for k,v in row.items() if k!='answers'}),flush=True)
            if row['max_seconds']>60 or row['errors']:
                save('model-scaling-stop.json',{'at_concurrency':n,'reason':'latency above 60 seconds or request failures; hardware saturation boundary, higher levels not exercised'})
                break
        # Repeat identical upload through durable intake; compare index contents.
        intake_load=[]
        for n in (8,16,32,64):
            start=time.monotonic()
            with ThreadPoolExecutor(max_workers=n) as ex:
                batch=list(ex.map(lambda i:upload('SYNTH-A',a,f'load-{n}-{i}.pdf'),range(n)))
            intake_seconds=time.monotonic()-start
            drained=wait_jobs(300)
            row={'concurrency':n,'scope':'HTTP native PDF intake; durable processing is serialized by design',
                'requests':n,'http_200':sum(r['http']==200 for r in batch),'intake_seconds':intake_seconds,
                'total_seconds':time.monotonic()-start,'queue_drained':drained,'queue':queue_status(),'uploads':batch}
            intake_load.append(row);save('upload-load.json',intake_load)
            print('UPLOAD_LOAD '+json.dumps({k:v for k,v in row.items() if k!='uploads'}),flush=True)
            if not drained or row['http_200']!=n:break
        import pickle,collections
        def index_inventory():
            out={}
            for p in (DATA/'faiss_index').glob('*/index.pkl'):
                if '.previous-' in p.parent.name or '.staging-' in p.parent.name:continue
                with p.open('rb') as f:store,mapping=pickle.load(f)
                chunks=[store.search(key) for key in mapping.values()]
                identities=[(d.metadata.get('source'),d.metadata.get('folder_id'),d.metadata.get('page'),d.page_content) for d in chunks]
                out[p.parent.name]={'count':len(chunks),'duplicate_identical_chunks':sum(c-1 for c in collections.Counter(identities).values() if c>1)}
            return out
        before=index_inventory();repeat=upload('SYNTH-A',a);wait_jobs();after=index_inventory()
        save('idempotence.json',{'before':before,'after':after,'upload':repeat,'same_counts':before==after})
        with sqlite3.connect(DATA/'expo.db') as c:integrity={'integrity':c.execute('pragma integrity_check').fetchone()[0],'foreign_key_violations':len(c.execute('pragma foreign_key_check').fetchall())}
        save('integrity.json',integrity)
        # A real restricted user must not be able to select the other project.
        import db
        restricted=db.get_user_by_username('synthetic-restricted')
        if not restricted:
            db.create_user('synthetic-restricted','synthetic-not-a-password-hash',role='user',by=user)
            restricted=db.get_user_by_username('synthetic-restricted')
        db.assign_member('SYNTH-A',restricted['id'],user)
        db.assign_folder_member(folders['SYNTH-A'],restricted['id'],user)
        restricted_token=jwt.encode({'sub':str(restricted['id']),'username':restricted['username'],'role':'user','ver':restricted['auth_version'],
            'exp':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=30)},auth.secret(),algorithm='HS256')
        with httpx.Client(base_url=base,headers={'Authorization':'Bearer '+restricted_token},timeout=30) as c:
            denied=c.post('/ask_stream',json={'project':'SYNTH-B','query':'What is the Plot Area?','messages':[],'k':8})
        save('access-isolation.json',{'other_project_http':denied.status_code,'body':denied.text,'pass':denied.status_code==403})
        # Restart only the isolated server, then query the persisted generations.
        server.terminate()
        try:server.wait(timeout=20)
        except subprocess.TimeoutExpired:server.kill();server.wait(timeout=10)
        server=subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port','8092'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT)
        restarted=False
        for _ in range(90):
            try:
                if httpx.get(base+'/health/ready',timeout=2).status_code==200:restarted=True;break
            except Exception:pass
            time.sleep(1)
        save('restart.json',{'ready':restarted,'queue':queue_status(),'indexes':index_inventory(),
            'answers':[ask('SYNTH-A','What is the Plot Area?','Documents/native-a.pdf'),ask('SYNTH-B','What is the Plot Area?','Documents/native-b.pdf')] if restarted else []})
    finally:
        stop.set();save('resources.json',stats)
        # This subprocess was created exclusively for this synthetic test.
        server.terminate()
        try:server.wait(timeout=20)
        except subprocess.TimeoutExpired:server.kill();server.wait(timeout=10)
        log.close()
