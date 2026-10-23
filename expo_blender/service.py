import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def root():
    from db import DATA_DIR
    default = Path(DATA_DIR)/'blender_jobs'
    return Path(os.getenv('EXPO_BLENDER_DATA', str(default))).resolve()


@contextmanager
def project_operation(project):
    """Share the purge lock across create/analyze/review/build operations."""
    import db
    from services.project_cleanup import active_project_operation
    with active_project_operation(db.DATA_DIR, project):
        yield


def job_dir(job_id):
    if not re.fullmatch(r'[0-9a-f]{32}', job_id):
        raise ValueError('Invalid job ID')
    path = root()/job_id
    if path.resolve().parent != root() or path.is_symlink():
        raise ValueError('Invalid job path')
    return path


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, data):
    path = Path(path)
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(tmp,path)


def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,allow_nan=False).encode()).hexdigest()


@contextmanager
def locked(folder):
    project = read(folder/'job.json')['project']
    with project_operation(project), _job_locked(folder):
        yield


@contextmanager
def _job_locked(folder):
    path = folder/'operation.lock'
    try: fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError: raise ValueError('Job is busy; if interrupted, see recovery instructions')
    try:
        os.write(fd, str(os.getpid()).encode()); os.close(fd)
        yield
    finally: path.unlink(missing_ok=True)


def event(folder, state, message):
    data = read(folder/'job.json')
    data.update(state=state, message=message)
    data.setdefault('events',[]).append({'time':datetime.now(timezone.utc).isoformat(),'state':state,'message':message})
    write(folder/'job.json',data)


def create(stream, project, owner, filename):
    with project_operation(project):
        return _create(stream, project, owner, filename)


def _create(stream, project, owner, filename):
    if Path(filename).suffix.lower() != '.pdf': raise ValueError('Upload a PDF drawing')
    job_id=uuid.uuid4().hex; folder=job_dir(job_id); folder.mkdir(parents=True)
    total=0
    try:
        with (folder/'source.pdf').open('wb') as target:
            while chunk := stream.read(1024*1024):
                total += len(chunk)
                if total > 30*1024*1024: raise ValueError('PDF limit is 30 MB')
                target.write(chunk)
        if not total or b'%PDF-' not in (folder/'source.pdf').read_bytes()[:1024]:
            raise ValueError('Invalid PDF header')
        write(folder/'job.json', {'id':job_id,'project':project,'owner':owner,'filename':Path(filename).name,
            'source_sha256':hashlib.sha256((folder/'source.pdf').read_bytes()).hexdigest(),
            'state':'queued','message':'Waiting for drawing analysis','events':[]})
    except Exception:
        (folder/'source.pdf').unlink(missing_ok=True)
        raise
    return status(job_id)


def status(job_id):
    folder=job_dir(job_id); data=read(folder/'job.json')
    for name in ('plan','review','approval'):
        if (folder/(name+'.json')).exists(): data[name]=read(folder/(name+'.json'))
    return data


def verify_source(folder):
    if hashlib.sha256((folder/'source.pdf').read_bytes()).hexdigest() != read(folder/'job.json')['source_sha256']:
        raise ValueError('Source PDF changed; upload it as a new job')


def analyze(job_id):
    folder=job_dir(job_id)
    with locked(folder):
        try:
            from .pdf_plan import inspect_pdf, propose, plan_to_dxf
            from .arch.planner import plan as furnish
            verify_source(folder)
            event(folder,'reading','Reading native PDF text and rendering every page')
            pages=inspect_pdf(folder/'source.pdf',folder); write(folder/'pages.json',pages)
            error=''
            for attempt in range(2):
                event(folder,'planning',f'Interpreting drawing evidence (attempt {attempt+1}/2)')
                proposal=propose(folder,pages,error).model_dump()
                write(folder/'plan.json',proposal)
                if proposal['unknowns']:
                    event(folder,'needs_input','Drawing has unresolved dimensions or unsupported geometry'); return
                try:
                    scene=plan_to_dxf(proposal,folder,len(pages)); break
                except ValueError as exc:
                    error=str(exc)
            else: raise ValueError(error)
            event(folder,'furnishing','Planning and validating catalog furniture')
            items=furnish(scene,os.getenv('EXPO_BLENDER_MODEL') or os.getenv('OPENAI_MODEL'))
            make_review(folder,proposal,scene,items)
        except Exception as exc:
            event(folder,'blocked',str(exc)[:1500])


def make_review(folder,plan,scene,items):
    from .arch.core import validate_furniture
    verify_source(folder)
    validate_furniture(scene,items)
    review={'source_sha256':read(folder/'job.json')['source_sha256'],'plan':plan,'scene':scene,'furniture':items,
        'limitations':['One floor, rectangular footprints only','PDF interpretation requires visual source review',
                      'No inferred roof, ceiling, glazing, door leaves, stairs or MEP',
                      'Furniture is proposed design; room clearance and conservative door buffers checked, not code compliance']}
    write(folder/'review.json',review)
    (folder/'approval.json').unlink(missing_ok=True)
    event(folder,'awaiting_approval','Check source pages, geometry, dimensions and furnishings before building')


def revise(job_id, plan, items):
    folder=job_dir(job_id)
    with locked(folder):
        from .pdf_plan import plan_to_dxf, DrawingPlan
        plan=DrawingPlan.model_validate(plan).model_dump()
        scene=plan_to_dxf(plan,folder,len(read(folder/'pages.json')))
        make_review(folder,plan,scene,items)
        write(folder/'plan.json',plan)
    return status(job_id)


def approve(job_id, expected_digest, reviewer):
    folder=job_dir(job_id)
    with locked(folder):
        verify_source(folder)
        review=read(folder/'review.json')
        if read(folder/'job.json')['state'] != 'awaiting_approval' or digest(review) != expected_digest:
            raise ValueError('Review changed or is not ready; reload and review it again')
        write(folder/'approval.json',{'review_sha256':digest(review),'reviewer':reviewer,'time':datetime.now(timezone.utc).isoformat()})
        event(folder,'approved','Human approved this exact source, geometry and furnishing review')


def blender_path():
    explicit=os.getenv('EXPO_BLENDER_EXE')
    if explicit:
        if not Path(explicit).is_file(): raise ValueError('EXPO_BLENDER_EXE does not exist')
        return explicit
    for version in ('4.5','5.2'):
        path=Path('C:/Program Files/Blender Foundation')/('Blender '+version)/'blender.exe'
        if path.is_file(): return str(path)
    raise ValueError('Set EXPO_BLENDER_EXE to your Blender executable')


def build(job_id, open_when_done=False, samples=128, resolution=1200):
    folder=job_dir(job_id)
    with locked(folder):
        try:
            from .arch.core import validate_furniture
            verify_source(folder)
            review=read(folder/'review.json'); approval=read(folder/'approval.json')
            if digest(review) != approval.get('review_sha256') or not approval.get('reviewer'):
                raise ValueError('Human approval missing or stale')
            if read(folder/'job.json')['state'] not in ('approved','complete','blocked'):
                raise ValueError('Job is not approved for building')
            validate_furniture(review['scene'],review['furniture'])
            exe=blender_path()
            event(folder,'building','Building source-based architecture and furnishing in Blender')
            output=folder/'render'; output.mkdir(exist_ok=True)
            for name in ('model.blend','render.png','manifest.json'): (output/name).unlink(missing_ok=True)
            script=Path(__file__).parent/'blender'/'build.py'
            with (output/'blender.log').open('w',encoding='utf-8') as log:
                subprocess.run([exe,'--background','--factory-startup','--python-exit-code','1','--python',str(script.resolve()),
                    '--',str((folder/'review.json').resolve()),str(output.resolve()),str(samples),str(resolution)],
                    stdout=log,stderr=subprocess.STDOUT,check=True,timeout=3600,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            for name in ('model.blend','render.png','manifest.json'):
                if not (output/name).is_file() or (output/name).stat().st_size == 0: raise ValueError('Missing Blender output: '+name)
            manifest=read(output/'manifest.json')
            if manifest['wall_parts'] != len(review['scene']['solids']): raise ValueError('Blender geometry count mismatch')
            event(folder,'complete','Model and Cycles render completed')
            if open_when_done: open_model(job_id)
        except Exception as exc: event(folder,'blocked',str(exc)[:1500])


def open_model(job_id):
    folder=job_dir(job_id)
    if read(folder/'job.json')['state'] != 'complete': raise ValueError('Build must complete before opening Blender')
    path=folder/'render'/'model.blend'
    # Visible application launch is explicitly requested by the UI/user.
    subprocess.Popen([blender_path(),'--disable-autoexec',str(path.resolve())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {'opened':True,'job_id':job_id}
