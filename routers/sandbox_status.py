"""Authenticated availability reporting; status checks never start a task."""
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
import auth

router = APIRouter()


def readiness():
    from services.container_sandbox import find_container_engine, get_container_image
    info = find_container_engine()
    if not info.get('daemon_running'):
        return {'ready': False, 'message': info.get('message', 'Engine unavailable')}
    try:
        get_container_image(info['path'])
    except Exception as exc:
        return {'ready': False, 'message': str(exc)}
    return {'ready': True, 'message': 'Isolated Python worker ready'}


@router.get('/agent/sandbox-status')
async def sandbox_status(request: Request):
    auth.require_user(request)
    return await run_in_threadpool(readiness)
