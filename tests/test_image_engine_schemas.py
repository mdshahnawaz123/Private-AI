"""
Unit tests for ComfyUI Image Engine Pydantic data schemas.
"""

import unittest
from pydantic import ValidationError
from services.image_engine.schemas import (
    EngineStatus,
    WorkflowParameter,
    WorkflowMetadata,
    JobSubmissionRequest,
    JobOutput,
    JobStatus,
)


class TestImageEngineSchemas(unittest.TestCase):
    def test_job_submission_valid(self):
        req = JobSubmissionRequest(
            project="ExpoProject",
            workflow_id="architecture_concept",
            prompt="Modern glass pavilion with green roof",
            width=1024,
            height=1024,
            steps=25,
            cfg=7.5,
        )
        self.assertEqual(req.width, 1024)
        self.assertEqual(req.height, 1024)
        self.assertEqual(req.steps, 25)

    def test_job_submission_rejects_non_multiple_of_64(self):
        with self.assertRaises(ValidationError) as ctx:
            JobSubmissionRequest(
                project="ExpoProject",
                workflow_id="architecture_concept",
                prompt="Modern pavilion",
                width=1000,  # Not a multiple of 64
                height=1024,
            )
        self.assertIn("multiple of 64", str(ctx.exception))

    def test_job_submission_clamps_min_max_dimensions(self):
        with self.assertRaises(ValidationError):
            JobSubmissionRequest(
                project="ExpoProject",
                workflow_id="architecture_concept",
                prompt="Modern pavilion",
                width=256,  # Below min (512)
                height=1024,
            )

        with self.assertRaises(ValidationError):
            JobSubmissionRequest(
                project="ExpoProject",
                workflow_id="architecture_concept",
                prompt="Modern pavilion",
                width=2048,  # Above max (1024)
                height=1024,
            )

    def test_engine_status_schema(self):
        status = EngineStatus(
            available=True,
            base_url="http://127.0.0.1:8188",
            device="NVIDIA GeForce RTX 5080",
            vram_total_mb=16384,
            vram_free_mb=12288,
            queue_running=0,
            queue_pending=1,
        )
        self.assertTrue(status.available)
        self.assertEqual(status.vram_total_mb, 16384)

    def test_workflow_metadata_schema(self):
        param = WorkflowParameter(
            name="prompt",
            type="string",
            label="Design Prompt",
            required=True,
        )
        meta = WorkflowMetadata(
            id="test_wf",
            name="Test Workflow",
            version="1.0.0",
            category="concept",
            required_models=["test_model.safetensors"],
            parameters=[param],
            available=True,
        )
        self.assertEqual(meta.id, "test_wf")
        self.assertEqual(len(meta.parameters), 1)

    def test_job_status_schema(self):
        output = JobOutput(
            output_id="out-123",
            filename="render_001.png",
            file_path="generated_images/render_001.png",
            width=1024,
            height=1024,
            seed=42,
        )
        job_status = JobStatus(
            job_id="job-999",
            project="ExpoProject",
            workflow_id="architecture_concept",
            status="completed",
            progress_percent=100,
            outputs=[output],
        )
        self.assertEqual(job_status.status, "completed")
        self.assertEqual(len(job_status.outputs), 1)


if __name__ == "__main__":
    unittest.main()
