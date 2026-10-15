"""
FastAPI route controller for the Expo Design AI Local Image Engine.

Provides project-isolated REST endpoints for:
- Live engine health and VRAM status
- Workflow discovery and schema introspection
- Image generation job submission (JSON and multipart sketch uploads)
- Job tracking, progress monitoring, and cancellation
- Output image and thumbnail retrieval with strict path containment
"""

import asyncio
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

import auth
import db
from services.image_engine.comfyui_client import ComfyUIClient
from services.image_engine.image_storage import ImageStorage, StorageSecurityError
from services.image_engine.job_service import JobService
from services.image_engine.schemas import (
    EngineStatus,
    JobOutput,
    JobStatus,
    JobSubmissionRequest,
    WorkflowMetadata,
    PromptEnhanceRequest,
    PromptEnhanceResponse,
)
from services.image_engine.workflow_registry import WorkflowNotFoundError, WorkflowRegistry

image_router = APIRouter(prefix="/api/image-engine", tags=["Image Engine"])

_client: Optional[ComfyUIClient] = None
_registry: Optional[WorkflowRegistry] = None
_storage: Optional[ImageStorage] = None
_job_service: Optional[JobService] = None


def get_job_service() -> JobService:
    """Retrieve or lazily initialize the singleton JobService."""
    global _client, _registry, _storage, _job_service
    if _job_service is None:
        _client = ComfyUIClient()
        _registry = WorkflowRegistry()
        _registry.discover_and_load()
        _storage = ImageStorage()
        _job_service = JobService(
            comfy_client=_client,
            workflow_registry=_registry,
            storage=_storage,
        )
    return _job_service


def set_job_service(service: Optional[JobService]) -> None:
    """Override singleton JobService for testing."""
    global _job_service
    _job_service = service


@image_router.get("/status", response_model=EngineStatus)
async def get_engine_status(request: Request):
    """
    Check the live availability and resource metrics of the local ComfyUI backend.
    Includes active model and queued job count.
    """
    auth.require_user(request)
    svc = get_job_service()
    status = await svc.client.check_health()
    status.queue_pending = svc._queue.qsize()
    if svc._running_job_id:
        status.queue_running = 1
    return status


@image_router.post("/service/start")
async def start_image_engine_service(request: Request):
    """Start the local AI Studio Engine process."""
    auth.require_roles(request, "admin")
    from services.image_engine.service_manager import start_engine
    return start_engine()


@image_router.post("/service/stop")
async def stop_image_engine_service(request: Request):
    """Stop the local AI Studio Engine process."""
    auth.require_roles(request, "admin")
    from services.image_engine.service_manager import stop_engine
    return stop_engine()


@image_router.get("/service/status")
async def get_service_lifecycle_status(request: Request):
    """Check whether the AI Studio Engine is reachable."""
    auth.require_user(request)
    from services.image_engine.service_manager import is_engine_reachable
    reachable = is_engine_reachable()
    return {
        "available": reachable,
        "status": "online" if reachable else "offline",
    }


@image_router.get("/workflows", response_model=List[WorkflowMetadata])
async def list_available_workflows(request: Request):
    """List all registered architectural ComfyUI workflows and their parameters."""
    auth.require_user(request)
    svc = get_job_service()
    health = await svc.client.check_health()
    if health.available:
        try:
            info = await svc.client.get_object_info(force_refresh=True)
            svc.registry.validate_against_comfy_object_info(info, validate_models=True)
        except Exception:
            for workflow in svc.registry.list_workflows():
                workflow.available = False
                workflow.unavailability_reason = "Renderer workflow readiness could not be verified"
    else:
        for workflow in svc.registry.list_workflows():
            workflow.available = False
            workflow.unavailability_reason = "Start ComfyUI to verify this workflow"
    return svc.registry.list_workflows()


@image_router.post("/jobs", response_model=JobStatus)
async def submit_image_job(request: Request):
    """
    Submit an architectural image generation job.
    Accepts application/json payload or multipart/form-data with sketch upload.
    Enforces project membership authorization.
    """
    content_type = request.headers.get("content-type", "")
    svc = get_job_service()

    if "application/json" in content_type:
        try:
            body = await request.json()
            sub_req = JobSubmissionRequest(**body)
        except Exception as exc:
            raise HTTPException(422, f"Invalid job request payload: {exc}")

        user = auth.require_project(request, sub_req.project)

        try:
            return await svc.submit_job(sub_req, user_id=user["id"])
        except (KeyError, WorkflowNotFoundError) as wf_err:
            raise HTTPException(404, str(wf_err))
        except ValueError as val_err:
            raise HTTPException(400, str(val_err))

    elif "multipart/form-data" in content_type:
        form = await request.form()
        project = form.get("project")
        if not project:
            raise HTTPException(400, "Field 'project' is required")
        project_str = str(project)

        user = auth.require_project(request, project_str)

        workflow_id = form.get("workflow_id")
        prompt = form.get("prompt")
        if not workflow_id or not prompt:
            raise HTTPException(400, "Fields 'workflow_id' and 'prompt' are required")

        input_image_path = None
        input_image_file = form.get("input_image")
        if input_image_file and hasattr(input_image_file, "read"):
            img_bytes = await input_image_file.read()
            if img_bytes:
                temp_job_id = f"input-{uuid.uuid4().hex[:8]}"
                try:
                    saved_path = svc.storage.save_input_image(
                        project=project_str,
                        job_id=temp_job_id,
                        image_bytes=img_bytes,
                        original_filename=getattr(input_image_file, "filename", "input.png"),
                    )
                    input_image_path = str(saved_path)
                except ValueError as img_err:
                    raise HTTPException(400, f"Invalid uploaded reference image: {img_err}")

        edit_mask_path = None
        mask_file = form.get('edit_mask')
        if mask_file and hasattr(mask_file, 'read'):
            mask_bytes = await mask_file.read()
            if not mask_bytes or len(mask_bytes) > 25 * 1024 * 1024:
                raise HTTPException(400, 'Mask must be nonempty and at most 25 MB')
            try:
                from services.image_engine.masked_edit import load_pair
                if not input_image_path:
                    raise ValueError('A mask requires an uploaded reference image')
                # Validate original mask before storage orientation normalization.
                import io
                from PIL import Image
                with Image.open(io.BytesIO(mask_bytes)) as mask_image:
                    if mask_image.format != 'PNG' or mask_image.getexif().get(274, 1) != 1:
                        raise ValueError('Mask must be an upright PNG')
                edit_mask_path = str(svc.storage.save_input_image(project_str, f'mask-{uuid.uuid4().hex[:8]}', mask_bytes, 'mask.png'))
                load_pair(input_image_path, edit_mask_path)
            except (ValueError, OSError) as exc:
                raise HTTPException(400, str(exc)) from exc

        try:
            width = int(form.get("width")) if form.get("width") else 1024
            height = int(form.get("height")) if form.get("height") else 1024
            steps = int(form.get("steps")) if form.get("steps") else 25
            cfg = float(form.get("cfg")) if form.get("cfg") else 7.0
            seed = int(form.get("seed")) if form.get("seed") else None

            enhance_prompt_val = str(form.get("enhance_prompt", "")).lower() in ("true", "1", "yes")

            sub_req = JobSubmissionRequest(
                project=project_str,
                workflow_id=str(workflow_id),
                prompt=str(prompt),
                negative_prompt=str(form.get("negative_prompt", "")) or None,
                width=width,
                height=height,
                steps=steps,
                cfg=cfg,
                seed=seed,
                architectural_style=str(form.get("architectural_style", "")) or None,
                building_type=str(form.get("building_type", "")) or None,
                input_image_path=input_image_path,
                edit_mask_path=edit_mask_path,
                enhance_prompt=enhance_prompt_val,
            )
        except Exception as exc:
            raise HTTPException(422, f"Invalid form parameters: {exc}")

        try:
            return await svc.submit_job(sub_req, user_id=user["id"])
        except (KeyError, WorkflowNotFoundError) as wf_err:
            raise HTTPException(404, str(wf_err))
        except ValueError as val_err:
            raise HTTPException(400, str(val_err))

    else:
        raise HTTPException(400, "Content-Type must be application/json or multipart/form-data")


@image_router.get("/jobs", response_model=List[JobStatus])
async def list_image_jobs(request: Request, project: str = Query(...), limit: int = Query(50)):
    """List recent image jobs within an authorized project."""
    auth.require_project(request, project)
    return get_job_service().list_jobs(project=project, limit=limit)


@image_router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str, request: Request):
    """Retrieve execution status, step progress, and outputs for a specific job."""
    auth.require_user(request)
    job_record = db.get_image_job(job_id)
    if not job_record:
        raise HTTPException(404, f"Job {job_id!r} not found")

    with db.SessionLocal() as s:
        proj = s.query(db.Project).filter_by(id=job_record["project_id"]).first()
        if not proj:
            raise HTTPException(404, "Owning project not found")
        project_name = proj.name

    auth.require_project(request, project_name)

    status = get_job_service().get_job_status(job_id)
    if not status:
        raise HTTPException(404, f"Job {job_id!r} not found")
    return status


@image_router.get("/jobs/{job_id}/outputs", response_model=List[JobOutput])
async def get_job_outputs(job_id: str, request: Request):
    """List output images produced by a completed job."""
    auth.require_user(request)
    job_record = db.get_image_job(job_id)
    if not job_record:
        raise HTTPException(404, f"Job {job_id!r} not found")

    with db.SessionLocal() as s:
        proj = s.query(db.Project).filter_by(id=job_record["project_id"]).first()
        if not proj:
            raise HTTPException(404, "Owning project not found")
        project_name = proj.name

    auth.require_project(request, project_name)

    status = get_job_service().get_job_status(job_id)
    return status.outputs if status else []


@image_router.get("/outputs/{output_id}/file")
async def get_output_file(output_id: str, request: Request):
    """
    Download full-resolution generated image file.
    Enforces project containment and access control.
    """
    auth.require_user(request)
    output = db.get_image_output(output_id)
    if not output:
        raise HTTPException(404, f"Output {output_id!r} not found")

    job = db.get_image_job(output["job_id"])
    if not job:
        raise HTTPException(404, "Parent job not found")

    with db.SessionLocal() as s:
        proj = s.query(db.Project).filter_by(id=job["project_id"]).first()
        if not proj:
            raise HTTPException(404, "Owning project not found")
        project_name = proj.name

    auth.require_project(request, project_name)

    try:
        file_path, _ = get_job_service().storage.get_output_paths(project_name, output_id)
    except StorageSecurityError as s_err:
        raise HTTPException(403, str(s_err))
    except FileNotFoundError as fnf_err:
        raise HTTPException(404, str(fnf_err))

    ext = file_path.suffix.lower()
    media_type = "video/mp4" if ext == ".mp4" else ("video/webm" if ext == ".webm" else "image/png")
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=output["filename"],
    )


@image_router.get("/outputs/{output_id}/thumb")
async def get_output_thumbnail(output_id: str, request: Request):
    """
    Serve 256x256 thumbnail for fast gallery rendering.
    Enforces project containment and access control.
    """
    auth.require_user(request)
    output = db.get_image_output(output_id)
    if not output:
        raise HTTPException(404, f"Output {output_id!r} not found")

    job = db.get_image_job(output["job_id"])
    if not job:
        raise HTTPException(404, "Parent job not found")

    with db.SessionLocal() as s:
        proj = s.query(db.Project).filter_by(id=job["project_id"]).first()
        if not proj:
            raise HTTPException(404, "Owning project not found")
        project_name = proj.name

    auth.require_project(request, project_name)

    try:
        file_path, thumb_path = get_job_service().storage.get_output_paths(project_name, output_id)
    except StorageSecurityError as s_err:
        raise HTTPException(403, str(s_err))
    except FileNotFoundError as fnf_err:
        raise HTTPException(404, str(fnf_err))

    target_path = thumb_path if (thumb_path and thumb_path.exists()) else file_path
    ext = target_path.suffix.lower()
    media_type = "video/mp4" if ext == ".mp4" else ("video/webm" if ext == ".webm" else "image/png")
    return FileResponse(
        path=str(target_path),
        media_type=media_type,
    )


@image_router.post("/jobs/{job_id}/cancel")
async def cancel_image_job(job_id: str, request: Request):
    """
    Cancel an active or queued image generation job.
    Only the job creator or an administrator can cancel.
    """
    u = auth.require_user(request)
    job_record = db.get_image_job(job_id)
    if not job_record:
        raise HTTPException(404, f"Job {job_id!r} not found")

    with db.SessionLocal() as s:
        proj = s.query(db.Project).filter_by(id=job_record["project_id"]).first()
        if not proj:
            raise HTTPException(404, "Owning project not found")
        project_name = proj.name

    auth.require_project(request, project_name)

    try:
        success = await get_job_service().cancel_job(
            job_id=job_id,
            user_id=u["id"],
            is_admin=(u.get("role") == "admin"),
        )
    except PermissionError as p_err:
        raise HTTPException(403, str(p_err))

    if not success:
        raise HTTPException(400, "Job cannot be cancelled (already completed or not found)")

    return {"job_id": job_id, "status": "cancelled"}


@image_router.post("/enhance-prompt", response_model=PromptEnhanceResponse)
async def enhance_prompt_endpoint(request: Request, payload: PromptEnhanceRequest):
    """
    Reason through and enhance an architectural design prompt using qwen3.5:9b.
    Immediately unloads VRAM to preserve RTX 5080 resources for image generation.
    """
    auth.require_user(request)
    from services.image_engine.design_brief import generate_design_brief
    try:
        res = await generate_design_brief(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return PromptEnhanceResponse(**res)


# ---------------------------------------------------------------------------
# Video Engine (Wan 2.2 TI2V 5B) Model Status & Weight Downloader
# ---------------------------------------------------------------------------
COMFY_MODELS_ROOT = Path("C:/3EH/ComfyUI/models")

WAN_MODELS_SPEC = {
    "diffusion": {
        "label": "Wan 2.2 TI2V 5B Diffusion Model",
        "filename": "wan2.2_ti2v_5B_fp16.safetensors",
        "alternatives": ["wan2.2_ti2v_5B_fp8_scaled.safetensors"],
        "folder": "diffusion_models",
        "url": "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors",
        "size_gb": 9.31,
    },
    "text_encoder": {
        "label": "UMT5-XXL FP8 Text Encoder",
        "filename": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "alternatives": ["umt5_xxl_fp16.safetensors"],
        "folder": "text_encoders",
        "url": "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        "size_gb": 6.27,
    },
    "vae": {
        "label": "Wan 2.2 VAE",
        "filename": "wan2.2_vae.safetensors",
        "alternatives": [],
        "folder": "vae",
        "url": "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan2.2_vae.safetensors",
        "size_gb": 1.31,
    },
}

_video_download_state: Dict[str, Any] = {
    "active": False,
    "current_file": None,
    "downloaded_bytes": 0,
    "total_bytes": 0,
    "percent": 0,
    "speed_mbps": 0.0,
    "status": "idle",
    "error": None,
}


@image_router.get("/video/status")
async def get_video_status(request: Request):
    """
    Check availability of Wan 2.2 TI2V 5B model weights in local ComfyUI instance.
    """
    auth.require_user(request)
    models_status = {}
    all_ready = True

    for key, spec in WAN_MODELS_SPEC.items():
        folder = COMFY_MODELS_ROOT / spec["folder"]
        target = folder / spec["filename"]
        present = target.exists() and target.stat().st_size > 1024 * 1024

        if not present:
            for alt in spec.get("alternatives", []):
                alt_path = folder / alt
                if alt_path.exists() and alt_path.stat().st_size > 1024 * 1024:
                    present = True
                    break

        if not present:
            all_ready = False

        models_status[key] = {
            "label": spec["label"],
            "filename": spec["filename"],
            "folder": spec["folder"],
            "present": present,
            "size_gb": spec["size_gb"],
            "url": spec["url"],
            "local_path": str(target),
        }

    engine_st = await get_job_service().client.check_health()

    return {
        "ready": all_ready and engine_st.available,
        "engine_available": engine_st.available,
        "device": engine_st.device,
        "vram_free_mb": engine_st.vram_free_mb,
        "models": models_status,
        "download_state": _video_download_state,
    }


async def _background_download_wan():
    global _video_download_state
    _video_download_state["active"] = True
    _video_download_state["error"] = None
    _video_download_state["status"] = "downloading"

    try:
        import time
        for key, spec in WAN_MODELS_SPEC.items():
            folder = COMFY_MODELS_ROOT / spec["folder"]
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / spec["filename"]

            # Skip if already present
            if target.exists() and target.stat().st_size > 1024 * 1024 * 50:
                continue

            _video_download_state["current_file"] = spec["filename"]
            _video_download_state["percent"] = 0
            part_path = target.with_suffix(".part")

            async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
                async with client.stream("GET", spec["url"], headers={"User-Agent": "Mozilla/5.0"}) as resp:
                    if resp.status_code != 200:
                        raise RuntimeError(f"HTTP {resp.status_code} downloading {spec['filename']}")
                    total = int(resp.headers.get("content-length", 0))
                    _video_download_state["total_bytes"] = total
                    downloaded = 0
                    start_t = time.time()

                    with open(part_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                            if not chunk:
                                break
                            f.write(chunk)
                            downloaded += len(chunk)
                            _video_download_state["downloaded_bytes"] = downloaded
                            if total > 0:
                                _video_download_state["percent"] = int(downloaded * 100 / total)
                            elapsed = time.time() - start_t
                            if elapsed > 0:
                                _video_download_state["speed_mbps"] = round((downloaded / (1024 * 1024)) / elapsed, 2)

            # Atomic rename once complete
            if part_path.exists():
                part_path.replace(target)

        _video_download_state["active"] = False
        _video_download_state["status"] = "completed"
        _video_download_state["percent"] = 100
    except Exception as exc:
        _video_download_state["active"] = False
        _video_download_state["status"] = "failed"
        _video_download_state["error"] = str(exc)


@image_router.post("/video/download-weights")
async def trigger_download_wan(request: Request):
    """
    Trigger automated background download of Wan 2.2 model weights into ComfyUI.
    """
    auth.require_user(request)
    if _video_download_state.get("active"):
        return {"status": "already_running", "download_state": _video_download_state}

    asyncio.create_task(_background_download_wan())
    return {"status": "started", "download_state": _video_download_state}

