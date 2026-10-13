"""
Expo Design AI - Local Image Engine Module.

Dedicated local image-generation subsystem interfacing with an isolated ComfyUI
instance. Provides asynchronous job tracking, workflow registration, and
secure project storage while respecting the NVIDIA RTX 5080 16 GB VRAM constraint.
"""

from services.image_engine.schemas import (
    EngineStatus,
    WorkflowMetadata,
    WorkflowParameter,
    JobSubmissionRequest,
    JobStatus,
    JobOutput,
)
from services.image_engine.comfyui_client import ComfyUIClient
from services.image_engine.workflow_registry import WorkflowRegistry
from services.image_engine.image_storage import ImageStorage
from services.image_engine.job_service import JobService
from services.image_engine.api import image_router, get_job_service

__all__ = [
    "EngineStatus",
    "WorkflowMetadata",
    "WorkflowParameter",
    "JobSubmissionRequest",
    "JobStatus",
    "JobOutput",
    "ComfyUIClient",
    "WorkflowRegistry",
    "ImageStorage",
    "JobService",
    "image_router",
    "get_job_service",
]
