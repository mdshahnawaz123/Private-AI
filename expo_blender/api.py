"""Mounted in Expo's existing app; uses existing auth and project membership."""
import os
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import auth
from . import service as svc

router=APIRouter(prefix='/api/blender',tags=['Drawing to Blender'])


def access(request,job_id,manage=False):
    auth.require_user(request)
    try: job=svc.status(job_id)
    except (ValueError,FileNotFoundError): raise HTTPException(404,'Job not found')
    auth.require_project(request,job['project'])
    if manage: auth.require_roles(request,'admin','lead')
    return job


def local(request):
    if not request.client or request.client.host not in ('127.0.0.1','::1','testclient'):
        raise HTTPException(403,'Opening Blender requires a request from this computer')


def call(fn,*args):
    try: return fn(*args)
    except (ValueError,FileNotFoundError) as exc: raise HTTPException(409,str(exc))


@router.get('/health')
def health(request:Request):
    auth.require_user(request)
    try: blender=svc.blender_path()
    except ValueError: blender=None
    return {'blender_available':bool(blender),'api_key_configured':bool(os.getenv('OPENAI_API_KEY')),
        'model':os.getenv('EXPO_BLENDER_MODEL') or os.getenv('OPENAI_MODEL'),
        'cloud_processing':'Selected PDF pages and text are sent to OpenAI only when you start analysis'}


@router.post('/jobs')
def create(request:Request,background:BackgroundTasks,project:str=Form(...),
           cloud_consent:bool=Form(False),file:UploadFile=File(...)):
    user=auth.require_roles(request,'admin','lead'); auth.require_project(request,project)
    if not cloud_consent: raise HTTPException(400,'Confirm OpenAI processing of this drawing')
    job=call(svc.create,file.file,project,user['id'],file.filename or '')
    background.add_task(svc.analyze,job['id'])
    return job


@router.get('/jobs/{job_id}')
def status(request:Request,job_id:str):
    job=access(request,job_id)
    if 'review' in job: job['review_digest']=svc.digest(job['review'])
    return job


class Revision(BaseModel):
    plan: dict
    furniture: list[dict] = Field(default_factory=list,max_length=100)


@router.post('/jobs/{job_id}/revise')
def revise(request:Request,job_id:str,payload:Revision):
    access(request,job_id,True)
    return call(svc.revise,job_id,payload.plan,payload.furniture)


class Approval(BaseModel):
    review_digest:str
    source_checked:bool
    open_blender:bool=False


@router.post('/jobs/{job_id}/approve')
def approve(request:Request,background:BackgroundTasks,job_id:str,payload:Approval):
    access(request,job_id,True)
    if not payload.source_checked: raise HTTPException(400,'Source review confirmation required')
    if payload.open_blender: local(request)
    user=auth.require_user(request)
    call(svc.approve,job_id,payload.review_digest,user['username'])
    background.add_task(svc.build,job_id,payload.open_blender)
    return {'state':'approved','id':job_id}


@router.post('/jobs/{job_id}/build')
def build(request:Request,background:BackgroundTasks,job_id:str):
    job=access(request,job_id,True)
    if 'review' not in job or job.get('approval',{}).get('review_sha256') != svc.digest(job['review']):
        raise HTTPException(409,'Current human approval required')
    if job['state'] not in ('approved','blocked','complete'): raise HTTPException(409,'Job is busy')
    background.add_task(svc.build,job_id)
    return {'queued':True,'id':job_id}


@router.post('/jobs/{job_id}/open')
def open_model(request:Request,job_id:str):
    access(request,job_id,True); local(request)
    return call(svc.open_model,job_id)


@router.get('/jobs/{job_id}/files/{name}')
def file(request:Request,job_id:str,name:str):
    access(request,job_id)
    mapping={n:'render/'+n for n in ('model.blend','render.png','manifest.json','blender.log')}
    mapping.update({n:n for n in ('source.pdf','derived.dxf','review.json','plan.json')})
    mapping.update({f'page-{p}.png':f'page-{p}.png' for p in range(1,5)})
    if name not in mapping: raise HTTPException(404,'Unknown artifact')
    path=svc.job_dir(job_id)/mapping[name]
    if not path.is_file(): raise HTTPException(404,'Artifact not ready')
    return FileResponse(path,filename=name)
