"""
Celery application for Expo Design AI (Phase 9).

Background job queue for heavy processing:
- OCR
- PDF processing
- CAD processing
- IFC processing
- Embedding generation
- Indexing
- Report generation
"""
import os
from celery import Celery

# Celery configuration
broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery_app = Celery(
    "expo_worker",
    broker=broker_url,
    backend=result_backend,
    include=["worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    worker_prefetch_multiplier=1,  # Fair task distribution
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks (memory)
)
