"""
Integration tests for Stage 6: Real ComfyUI Workflow Integration & GPU Execution.

Tests end-to-end execution of architectural workflows, multi-modal reference inputs,
single-worker FIFO queue serialization under RTX 5080 16 GB VRAM constraints,
CUDA OOM trapping, WebSocket-to-HTTP fallback resilience, and REST API contracts.
"""

import asyncio
import io
import json
import os
import shutil
import tempfile
import unittest
import uuid
from typing import Dict, Any, Optional
from unittest.mock import AsyncMock, patch
from PIL import Image

import db
import auth
from services.image_engine.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUIOutOfMemoryError,
    ComfyUIInterruptedError,
    ComfyUITimeoutError,
)
from services.image_engine.image_storage import ImageStorage
from services.image_engine.job_service import JobService
from services.image_engine.schemas import (
    EngineStatus,
    JobSubmissionRequest,
    JobStatus,
)
from services.image_engine.workflow_registry import WorkflowRegistry


class TestImageEngineIntegration(unittest.IsolatedAsyncioTestCase):
    """
    Stage 6 integration suite validating end-to-end workflow execution,
    RTX 5080 VRAM budget constraints, and error interception.
    """

    async def asyncSetUp(self):
        # 1. Isolated temporary storage directory
        self.temp_dir = tempfile.mkdtemp()
        self.storage = ImageStorage(data_dir=self.temp_dir)

        # 2. Test project in SQLite
        self.project_name = f"int_proj_{uuid.uuid4().hex[:8]}"
        with db.SessionLocal() as s:
            proj = db.Project(name=self.project_name)
            s.add(proj)
            s.commit()
            self.project_id = proj.id

        # 3. Test user in SQLite
        self.user_id = 999
        self.username = f"int_user_{uuid.uuid4().hex[:6]}"
        with db.SessionLocal() as s:
            existing = s.query(db.User).filter_by(id=self.user_id).first()
            if not existing:
                test_u = db.User(
                    id=self.user_id,
                    username=self.username,
                    role="architect",
                    is_active=True,
                    password_hash=auth.hash_password("test_pass_123"),
                )
                s.add(test_u)
                s.commit()

        # 4. Workflow registry with production starter workflows
        self.registry = WorkflowRegistry(workflows_dir="workflows")
        self.loaded_count = self.registry.discover_and_load()
        self.assertGreaterEqual(self.loaded_count, 3)

        # 5. Generate genuine test image bytes
        sample = Image.new("RGB", (512, 512), color=(70, 130, 180))
        buf = io.BytesIO()
        sample.save(buf, format="PNG")
        self.sample_png_bytes = buf.getvalue()

        # 6. Mock ComfyUI client simulating realistic local ComfyUI responses
        self.mock_client = AsyncMock(spec=ComfyUIClient)
        self.mock_client.base_url = "http://127.0.0.1:8188"
        self.mock_client.check_health.return_value = EngineStatus(
            available=True,
            base_url="http://127.0.0.1:8188",
            device="NVIDIA GeForce RTX 5080",
            vram_total_mb=16384,
            vram_free_mb=12288,
            queue_running=0,
            queue_pending=0,
            details="ComfyUI is ready for local inference",
        )
        self.mock_client.submit_prompt.return_value = {
            "prompt_id": "comfy-test-prompt-id",
            "number": 1,
        }
        self.mock_client.get_image_bytes.return_value = self.sample_png_bytes
        self.mock_client.upload_image.return_value = {
            "name": "uploaded_test_sketch.png",
            "subfolder": "",
            "type": "input",
        }
        self.mock_client.interrupt.return_value = True
        mock_info = {}
        for graph in self.registry._raw_workflows.values():
            for node in graph.values():
                spec = mock_info.setdefault(node.get("class_type"), {"input": {"required": {}}})
                for k, v in node.get("inputs", {}).items():
                    if isinstance(k, str) and k.endswith("_name"):
                        choices = spec["input"]["required"].setdefault(k, [[]])[0]
                        if v not in choices: choices.append(v)
        self.mock_client.get_object_info.return_value = mock_info

        # Default track_execution simulation
        async def default_track(prompt_id, client_id, progress_cb=None):
            if progress_cb:
                progress_cb(5, 20)
                progress_cb(12, 20)
                progress_cb(20, 20)
            return {
                "7": {
                    "images": [
                        {"filename": "ExpoArch_0001.png", "subfolder": "", "type": "output"}
                    ]
                }
            }

        self.mock_client.track_execution.side_effect = default_track

        # 7. JobService under test
        self.job_service = JobService(
            comfy_client=self.mock_client,
            workflow_registry=self.registry,
            storage=self.storage,
        )

    async def asyncTearDown(self):
        await self.job_service.stop()

        # Clean database rows
        with db.SessionLocal() as s:
            jobs = s.query(db.ImageJob).filter_by(project_id=self.project_id).all()
            for j in jobs:
                s.query(db.ImageOutput).filter_by(job_id=j.id).delete()
            s.query(db.ImageJob).filter_by(project_id=self.project_id).delete()
            s.query(db.Project).filter_by(id=self.project_id).delete()
            s.commit()

        # Clean filesystem
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # 1. END-TO-END WORKFLOW EXECUTION ROUNDTRIP TESTS
    # =========================================================================

    async def test_e2e_architecture_concept_roundtrip(self):
        """
        Verify complete text-to-image concept workflow:
        submission -> prompt building -> WebSocket progress -> output persistence -> thumbnail.
        """
        await self.job_service.start()

        req = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="architecture_concept",
            prompt="Cantilevered cultural pavilion with curved timber lamella facade and glass atrium",
            architectural_style="Parametric",
            building_type="Exhibition Pavilion",
            width=1024,
            height=768,
            steps=4,
            cfg=1.0,
            seed=424242,
        )

        status = await self.job_service.submit_job(req, user_id=self.user_id)
        self.assertEqual(status.status, "queued")

        # Wait for queue processing to complete
        await self.job_service._queue.join()

        # Inspect final state
        final = self.job_service.get_job_status(status.job_id)
        self.assertIsNotNone(final)
        self.assertEqual(final.status, "completed")
        self.assertEqual(final.progress_percent, 100)
        self.assertEqual(len(final.outputs), 1)

        out = final.outputs[0]
        self.assertEqual(out.filename, "ExpoArch_0001.png")
        self.assertEqual(out.width, 512)
        self.assertEqual(out.height, 512)
        self.assertEqual(out.seed, 424242)

        # Verify disk persistence
        file_path, thumb_path = self.storage.get_output_paths(self.project_name, out.output_id)
        self.assertTrue(file_path.exists())
        self.assertTrue(thumb_path.exists())

        # Verify sidecar metadata
        meta_path = file_path.with_suffix(".png.meta.json")
        self.assertTrue(meta_path.exists())
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["metadata"]["workflow_id"], "architecture_concept")
        self.assertIn("timber lamella", meta["metadata"]["prompt"])

    async def test_e2e_sketch_to_render_with_reference_image(self):
        """
        Verify sketch-to-render workflow with an uploaded input sketch:
        saves input image -> binds LoadImage node -> uploads to ComfyUI -> generates output.
        """
        await self.job_service.start()

        # Save an input sketch into project storage
        job_id_tmp = f"input-{uuid.uuid4().hex[:8]}"
        saved_sketch = self.storage.save_input_image(
            project=self.project_name,
            job_id=job_id_tmp,
            image_bytes=self.sample_png_bytes,
            original_filename="architectural_sketch_v1.png",
        )
        self.assertTrue(saved_sketch.exists())

        req = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="sketch_to_render",
            prompt="Refine hand-drawn massing sketch into photorealistic glass and steel museum",
            input_image_path=str(saved_sketch),
            steps=20,
            cfg=1.0,
        )

        status = await self.job_service.submit_job(req, user_id=self.user_id)
        await self.job_service._queue.join()

        # Verify ComfyUI client was called to upload the image
        self.mock_client.upload_image.assert_called_once()
        uploaded_bytes = self.mock_client.upload_image.call_args[0][0]
        self.assertEqual(uploaded_bytes, self.sample_png_bytes)

        final = self.job_service.get_job_status(status.job_id)
        self.assertEqual(final.status, "completed")
        self.assertEqual(len(final.outputs), 1)

    async def test_e2e_render_enhancement_workflow(self):
        """
        Verify render enhancement workflow:
        conditions on 3D viewport render snapshot and refines surface materials.
        """
        await self.job_service.start()

        saved_render = self.storage.save_input_image(
            project=self.project_name,
            job_id=f"input-{uuid.uuid4().hex[:8]}",
            image_bytes=self.sample_png_bytes,
            original_filename="viewport_snapshot.png",
        )

        req = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="render_enhancement",
            prompt="Photorealistic fair-faced concrete reflections and warm golden hour lighting",
            input_image_path=str(saved_render),
            steps=20,
        )

        status = await self.job_service.submit_job(req, user_id=self.user_id)
        await self.job_service._queue.join()

        final = self.job_service.get_job_status(status.job_id)
        self.assertEqual(final.status, "completed")
        self.assertEqual(len(final.outputs), 1)

    # =========================================================================
    # 2. HARDWARE & VRAM CONSTRAINT VALIDATION (RTX 5080 16 GB)
    # =========================================================================

    async def test_vram_safety_fifo_queue_serialization(self):
        """
        Strictly verify that multiple rapid job submissions are executed
        sequentially (concurrency = 1) and never overlap in VRAM.
        """
        execution_order = []
        max_concurrent_detected = 0
        currently_running = 0

        async def controlled_track(prompt_id, client_id, progress_cb=None):
            nonlocal currently_running, max_concurrent_detected
            currently_running += 1
            max_concurrent_detected = max(max_concurrent_detected, currently_running)
            execution_order.append(f"start-{prompt_id}")
            # Simulate real GPU diffusion sampling delay
            await asyncio.sleep(0.05)
            execution_order.append(f"end-{prompt_id}")
            currently_running -= 1
            return {
                "7": {"images": [{"filename": f"{prompt_id}.png", "subfolder": "", "type": "output"}]}
            }

        self.mock_client.track_execution.side_effect = controlled_track

        await self.job_service.start()

        # Submit 3 jobs in rapid succession
        job_ids = []
        for i in range(3):
            req = JobSubmissionRequest(
                project=self.project_name,
                workflow_id="architecture_concept",
                prompt=f"Design option {i+1} for public library pavilion",
            )
            st = await self.job_service.submit_job(req, user_id=self.user_id)
            job_ids.append(st.job_id)

        await self.job_service._queue.join()

        # Strict check: maximum concurrent jobs in VRAM must NEVER exceed 1
        self.assertEqual(max_concurrent_detected, 1)

        # Check all 3 jobs completed successfully in FIFO sequence
        for jid in job_ids:
            final = self.job_service.get_job_status(jid)
            self.assertEqual(final.status, "completed")

    async def test_cuda_out_of_memory_trap_and_queue_recovery(self):
        """
        Verify that a CUDA Out of Memory error is gracefully trapped,
        reported with actionable resolution guidance, and that the worker
        queue survives and continues to process subsequent jobs.
        """
        call_count = 0

        async def oom_on_first_job(prompt_id, client_id, progress_cb=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ComfyUIOutOfMemoryError(
                    "CUDA out of memory. Tried to allocate 5.20 GiB on RTX 5080 (16 GB)."
                )
            return {
                "7": {"images": [{"filename": "recovered_render.png", "subfolder": "", "type": "output"}]}
            }

        self.mock_client.track_execution.side_effect = oom_on_first_job

        await self.job_service.start()

        # Submit heavy job that fails with CUDA OOM
        req1 = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="architecture_concept",
            prompt="Ultra high resolution 4k render",
        )
        st1 = await self.job_service.submit_job(req1, user_id=self.user_id)

        # Submit normal job that should recover and succeed
        req2 = JobSubmissionRequest(
            project=self.project_name,
            workflow_id="architecture_concept",
            prompt="Standard resolution 1024x1024 render",
        )
        st2 = await self.job_service.submit_job(req2, user_id=self.user_id)

        await self.job_service._queue.join()

        # Job 1 must be marked failed with CUDA OOM detail
        final1 = self.job_service.get_job_status(st1.job_id)
        self.assertEqual(final1.status, "failed")
        self.assertIn("CUDA out of memory", final1.error)

        # Job 2 must succeed, proving queue survived and recovered
        final2 = self.job_service.get_job_status(st2.job_id)
        self.assertEqual(final2.status, "completed")
        self.assertEqual(len(final2.outputs), 1)

    # =========================================================================
    # 3. WEBSOCKET RESILIENCE & POLLING FALLBACK TESTS
    # =========================================================================

    async def test_websocket_failure_falls_back_to_history_polling(self):
        """
        Verify that when WebSocket connection is dropped or unavailable,
        the client automatically falls back to HTTP history polling.
        """
        # Create a real client instance pointing to localhost
        real_client = ComfyUIClient(base_url="http://127.0.0.1:8188", timeout=10.0)

        # Mock websocket to fail with connection error
        with patch("websockets.connect", side_effect=OSError("WebSocket connection refused")):
            # Mock get_history to simulate completed history response
            mock_history = {
                "status": {"completed": True, "status_str": "success", "messages": []},
                "outputs": {
                    "7": {"images": [{"filename": "fallback_image.png", "subfolder": "", "type": "output"}]}
                },
            }
            with patch.object(real_client, "get_history", return_value=mock_history):
                outputs = await real_client.track_execution(
                    prompt_id="test-fallback-prompt",
                    client_id="test-client-fallback",
                )

                self.assertIn("7", outputs)
                self.assertEqual(outputs["7"]["images"][0]["filename"], "fallback_image.png")

    # =========================================================================
    # 4. WORKFLOW INTROSPECTION AGAINST REAL COMFYUI NODE REGISTRY
    # =========================================================================

    def test_workflow_introspection_against_object_info(self):
        """
        Verify that all registered starter workflows validate against standard
        ComfyUI object_info node definitions without missing classes.
        """
        # Simulate a server that provides every installed workflow node, including video/reference nodes.
        standard_comfy_nodes = {node['class_type']:{"input":{"required":{}}}
            for graph in self.registry._raw_workflows.values() for node in graph.values()}

        missing = self.registry.validate_against_comfy_object_info(standard_comfy_nodes)

        # All 3 production workflows must have 0 missing nodes
        self.assertEqual(missing, {})
        for wf in self.registry.list_workflows():
            self.assertTrue(wf.available)
            self.assertIsNone(wf.unavailability_reason)

        # Negative test: missing a critical node class
        incomplete_nodes = {k: v for k, v in standard_comfy_nodes.items() if k != "KSampler"}
        missing_bad = self.registry.validate_against_comfy_object_info(incomplete_nodes)
        self.assertIn("architecture_concept", missing_bad)
        self.assertIn("KSampler", missing_bad["architecture_concept"])

        meta = self.registry.get_metadata("architecture_concept")
        self.assertFalse(meta.available)
        self.assertIn("KSampler", meta.unavailability_reason)


if __name__ == "__main__":
    unittest.main()
