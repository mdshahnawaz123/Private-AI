"""
Job service and FIFO scheduler for the Expo Design AI Local Image Engine.

Provides persistent, restart-safe job tracking, queue management, and execution
dispatching to ComfyUI. Strictly enforces single-worker concurrency to protect
the 16 GB VRAM envelope on the NVIDIA RTX 5080.
"""

import asyncio
import datetime
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List

from loguru import logger

import db
from services.image_engine.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUIOutOfMemoryError,
    ComfyUITimeoutError,
    ComfyUIInterruptedError,
)
from services.image_engine.image_storage import ImageStorage
from services.image_engine.schemas import (
    JobSubmissionRequest,
    JobStatus,
    JobOutput,
)
from services.image_engine.workflow_registry import WorkflowRegistry


class JobService:
    """
    Coordinates image generation jobs, queue serialization, execution tracking,
    and output persistence into project storage.
    """

    def __init__(
        self,
        comfy_client: ComfyUIClient,
        workflow_registry: WorkflowRegistry,
        storage: Optional[ImageStorage] = None,
    ):
        self.client = comfy_client
        self.registry = workflow_registry
        self.storage = storage or ImageStorage()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._running_job_id: Optional[str] = None
        self._stopping = False

    async def start(self) -> None:
        """Initialize worker loop and reconcile interrupted jobs from database."""
        if self._worker_task and not self._worker_task.done():
            return

        self._stopping = False
        # Reconcile stale jobs from prior process crash
        self._reconcile_interrupted_jobs()

        self._worker_task = asyncio.create_task(self._worker_loop(), name="image-engine-worker")
        logger.info("Image Engine single-worker scheduler started")

    async def stop(self) -> None:
        """Stop background scheduler worker gracefully."""
        self._stopping = True
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("Image Engine scheduler stopped")

    def _reconcile_interrupted_jobs(self) -> None:
        """Mark any jobs left in 'running' state from previous process as failed."""
        try:
            with db.SessionLocal() as s:
                stale_jobs = s.query(db.ImageJob).filter_by(status="running").all()
                for job in stale_jobs:
                    job.status = "failed"
                    job.error_message = "Server restarted while generation was in-flight; please resubmit."
                    job.completed_at = datetime.datetime.utcnow()
                s.commit()
                if stale_jobs:
                    logger.warning(f"Reconciled {len(stale_jobs)} interrupted running image jobs to failed")
        except Exception as exc:
            logger.error(f"Failed to reconcile stale image jobs: {exc}")

    async def submit_job(self, request: JobSubmissionRequest, user_id: int) -> JobStatus:
        """
        Validate, create, and enqueue a new image generation job.
        Verifies project access and workflow existence.
        """
        # 1. Verify project exists in database
        with db.SessionLocal() as s:
            project_row = s.query(db.Project).filter_by(name=request.project).first()
            if not project_row:
                raise ValueError(f"Project {request.project!r} does not exist")
            project_id = project_row.id

        # 2. Verify workflow is registered
        graph = self.registry.get_workflow(request.workflow_id)
        if any(node.get("class_type") == "Flux2Scheduler" for node in graph.values()):
            request = request.model_copy(update={"steps": 4, "cfg": 1.0})
        health = await self.client.check_health()
        if not health.available:
            raise ValueError(f"Image renderer unavailable at {self.client.base_url}. Start ComfyUI before generating.")
        try:
            info = await self.client.get_object_info(force_refresh=True)
            missing = self.registry.validate_against_comfy_object_info(info, validate_models=True)
        except Exception as exc:
            raise ValueError(f"Could not verify image renderer readiness: {exc}") from exc
        if request.workflow_id in missing:
            raise ValueError("Workflow unavailable: " + "; ".join(missing[request.workflow_id]))

        job_id = f"imgjob-{uuid.uuid4().hex[:12]}"

        # 3. Insert into database
        db.create_image_job(
            job_id=job_id,
            project_id=project_id,
            user_id=user_id,
            workflow_id=request.workflow_id,
            input_params=request.model_dump(),
        )

        # 4. Enqueue for single-worker execution
        await self._queue.put((job_id, request, user_id))

        # Audit log creation
        try:
            db.audit(
                user_id=user_id,
                action="image.job.create",
                project=request.project,
                target=job_id,
                detail={"workflow_id": request.workflow_id, "prompt": request.prompt[:200]},
            )
        except Exception:
            pass

        return self.get_job_status(job_id) or JobStatus(
            job_id=job_id,
            project=request.project,
            workflow_id=request.workflow_id,
            status="queued",
            progress_percent=0,
            queue_position=self._queue.qsize(),
        )

    def get_job_status(self, job_id: str) -> Optional[JobStatus]:
        """Fetch real-time job status with outputs from the database."""
        record = db.get_image_job(job_id)
        if not record:
            return None

        # Resolve project name
        project_name = "default"
        with db.SessionLocal() as s:
            proj = s.query(db.Project).filter_by(id=record["project_id"]).first()
            if proj:
                project_name = proj.name

        outputs = [
            JobOutput(
                output_id=o["id"],
                filename=o["filename"],
                file_path=o["file_path"],
                thumbnail_url=f"/api/image-engine/outputs/{o['id']}/thumb" if o.get("thumbnail_path") else None,
                download_url=f"/api/image-engine/outputs/{o['id']}/file",
                width=o["width"],
                height=o["height"],
                seed=o.get("seed"),
                metadata=o.get("metadata", {}),
            )
            for o in record.get("outputs", [])
        ]

        # Calculate duration if completed
        duration_sec = None
        if record.get("created_at") and record.get("completed_at"):
            try:
                t0 = datetime.datetime.fromisoformat(record["created_at"])
                t1 = datetime.datetime.fromisoformat(record["completed_at"])
                duration_sec = round((t1 - t0).total_seconds(), 2)
            except Exception:
                pass

        # Calculate queue position if queued
        queue_pos = None
        if record["status"] == "queued":
            queue_pos = max(1, self._queue.qsize())

        input_params = record.get("input_params") or {}
        reasoning = input_params.get("reasoning")
        enhanced_prompt = input_params.get("enhanced_prompt")
        if not reasoning and record.get("outputs"):
            first_meta = record["outputs"][0].get("metadata") or {}
            reasoning = first_meta.get("reasoning")
            enhanced_prompt = first_meta.get("enhanced_prompt") or first_meta.get("prompt")

        return JobStatus(
            job_id=record["id"],
            project=project_name,
            workflow_id=record["workflow_id"],
            status=record["status"],
            progress_percent=record["progress"],
            current_step=record.get("current_step"),
            total_steps=record.get("total_steps"),
            queue_position=queue_pos,
            error=record.get("error_message"),
            reasoning=reasoning,
            enhanced_prompt=enhanced_prompt,
            outputs=outputs,
            created_at=record.get("created_at"),
            completed_at=record.get("completed_at"),
            execution_duration_sec=duration_sec,
        )

    async def cancel_job(self, job_id: str, user_id: int, is_admin: bool = False) -> bool:
        """
        Cancel a queued or running image generation job.
        If running on ComfyUI, sends interrupt signal.
        """
        record = db.get_image_job(job_id)
        if not record:
            return False

        if record["status"] in ("completed", "failed", "cancelled"):
            return False

        if not is_admin and record["user_id"] != user_id:
            raise PermissionError("Cannot cancel another user's job")

        if record["status"] == "running":
            await self.client.interrupt()

        db.update_image_job(
            job_id,
            status="cancelled",
            error_message="Job was cancelled by user request",
            completed_at=datetime.datetime.utcnow(),
        )

        try:
            db.audit(
                user_id=user_id,
                action="image.job.cancel",
                target=job_id,
                detail={"previous_status": record["status"]},
            )
        except Exception:
            pass

        return True

    def list_jobs(self, project: str, user_id: Optional[int] = None, limit: int = 50) -> List[JobStatus]:
        """List recent jobs for a project."""
        with db.SessionLocal() as s:
            proj = s.query(db.Project).filter_by(name=project).first()
            if not proj:
                return []
            project_id = proj.id

        rows = db.list_image_jobs(project_id=project_id, user_id=user_id, limit=limit)
        results = []
        for r in rows:
            st = self.get_job_status(r["id"])
            if st:
                results.append(st)
        return results

    async def _worker_loop(self) -> None:
        """FIFO worker task loop processing one job at a time."""
        while not self._stopping:
            try:
                job_id, request, user_id = await self._queue.get()
                self._running_job_id = job_id
                try:
                    await self._execute_single_job(job_id, request, user_id)
                finally:
                    self._running_job_id = None
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception(f"Unexpected error in Image Engine worker loop: {exc}")
                await asyncio.sleep(1.0)

    async def _execute_single_job(
        self, job_id: str, request: JobSubmissionRequest, user_id: int
    ) -> None:
        """Execute a single job against ComfyUI and save results."""
        # Re-check status in DB; if cancelled while queued, skip execution
        current = db.get_image_job(job_id)
        if not current or current["status"] == "cancelled":
            logger.info(f"Skipping cancelled job {job_id}")
            return

        db.update_image_job(job_id, status="running", progress=5)

        try:
            # 1. Preflight ComfyUI reachability check
            health = await self.client.check_health()
            if not health.available:
                raise ComfyUIError(
                    f"ComfyUI is currently offline on {self.client.base_url}. "
                    "Start ComfyUI to execute image generation."
                )

            # 1.5. Architectural reasoning prompt enhancement
            reasoning_summary = None
            orig_prompt = request.prompt
            if getattr(request, "enhance_prompt", False):
                db.update_image_job(job_id, progress=8)
                try:
                    from services.image_engine.prompt_reasoner import enhance_architectural_prompt
                    enhanced_res = await enhance_architectural_prompt(
                        prompt=request.prompt,
                        building_type=request.building_type,
                        architectural_style=request.architectural_style,
                        unload_vram=True,
                    )
                    if enhanced_res.get("success"):
                        reasoning_summary = enhanced_res.get("reasoning")
                        enhanced_text = enhanced_res.get("enhanced_prompt")
                        request = request.model_copy(update={"prompt": enhanced_text})
                        with db.SessionLocal() as s:
                            job_row = s.query(db.ImageJob).filter_by(id=job_id).first()
                            if job_row:
                                params = dict(job_row.input_params or {})
                                params["enhanced_prompt"] = enhanced_text
                                params["reasoning"] = reasoning_summary
                                params["original_prompt"] = orig_prompt
                                job_row.input_params = params
                                s.commit()
                except Exception as r_err:
                    logger.warning(f"Reasoning prompt enhancement failed: {r_err}")

            # 2. Build Prompt API graph
            prompt_graph = self.registry.build_prompt_graph(request)

            # 3. If an input image was provided (sketch or render), upload to ComfyUI
            if request.input_image_path:
                with open(request.input_image_path, "rb") as f:
                    img_bytes = f.read()
                upload_name = f"{job_id}_{Path(request.input_image_path).name}"
                upload_res = await self.client.upload_image(img_bytes, upload_name)
                # Rebind LoadImage node inputs with ComfyUI's saved filename
                for node in prompt_graph.values():
                    if node.get("class_type") == "LoadImage":
                        node["inputs"]["image"] = upload_res.get("name", upload_name)

            # 4. Submit prompt to ComfyUI
            client_id = f"expo-{uuid.uuid4().hex[:8]}"
            submission = await self.client.submit_prompt(prompt_graph, client_id=client_id)
            comfy_prompt_id = submission["prompt_id"]

            db.update_image_job(job_id, comfy_prompt_id=comfy_prompt_id, progress=15)

            # 5. Track execution via WebSocket (with polling fallback)
            def on_progress(current_step: int, total_steps: int):
                pct = 15 + int((current_step / max(1, total_steps)) * 75)
                db.update_image_job(
                    job_id,
                    progress=min(90, pct),
                    current_step=current_step,
                    total_steps=total_steps,
                )

            outputs_map = await self.client.track_execution(
                prompt_id=comfy_prompt_id,
                client_id=client_id,
                progress_cb=on_progress,
            )

            db.update_image_job(job_id, progress=92)

            # 6. Retrieve and persist generated image files
            saved_count = 0
            for node_id, node_out in outputs_map.items():
                images = node_out.get("images", [])
                for img_info in images:
                    fn = img_info.get("filename")
                    subfolder = img_info.get("subfolder", "")
                    ftype = img_info.get("type", "output")
                    if fn:
                        img_bytes = await self.client.get_image_bytes(
                            filename=fn, subfolder=subfolder, folder_type=ftype
                        )
                        self.storage.save_output_image(
                            project=request.project,
                            job_id=job_id,
                            image_bytes=img_bytes,
                            filename=fn,
                            seed=request.seed,
                            metadata={
                                "workflow_id": request.workflow_id,
                                "prompt": request.prompt,
                                "original_prompt": orig_prompt,
                                "reasoning": reasoning_summary,
                                "architectural_style": request.architectural_style,
                                "building_type": request.building_type,
                                "comfy_prompt_id": comfy_prompt_id,
                                "steps": request.steps,
                                "cfg": request.cfg,
                            },
                        )
                        saved_count += 1

            if saved_count == 0:
                raise ComfyUIError("Workflow completed but produced no output images")

            # 7. Mark completed
            db.update_image_job(
                job_id,
                status="completed",
                progress=100,
                completed_at=datetime.datetime.utcnow(),
            )

            try:
                db.audit(
                    user_id=user_id,
                    action="image.job.complete",
                    project=request.project,
                    target=job_id,
                    detail={"output_count": saved_count},
                )
            except Exception:
                pass

            logger.info(f"Image job {job_id} successfully completed ({saved_count} images)")

        except ComfyUIOutOfMemoryError as oom_err:
            logger.error(f"Image job {job_id} failed with CUDA OOM: {oom_err}")
            db.update_image_job(
                job_id,
                status="failed",
                error_message=str(oom_err),
                completed_at=datetime.datetime.utcnow(),
            )
        except ComfyUIInterruptedError:
            logger.warning(f"Image job {job_id} was interrupted")
            db.update_image_job(
                job_id,
                status="cancelled",
                error_message="Generation was cancelled or interrupted",
                completed_at=datetime.datetime.utcnow(),
            )
        except ComfyUITimeoutError as t_err:
            logger.error(f"Image job {job_id} timed out: {t_err}")
            db.update_image_job(
                job_id,
                status="failed",
                error_message=str(t_err),
                completed_at=datetime.datetime.utcnow(),
            )
        except Exception as gen_err:
            logger.exception(f"Image job {job_id} failed: {gen_err}")
            db.update_image_job(
                job_id,
                status="failed",
                error_message=str(gen_err),
                completed_at=datetime.datetime.utcnow(),
            )
            try:
                db.audit(
                    user_id=user_id,
                    action="image.job.fail",
                    project=request.project,
                    target=job_id,
                    detail={"error": str(gen_err)[:300]},
                )
            except Exception:
                pass
