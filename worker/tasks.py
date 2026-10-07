"""
Celery tasks for Expo Design AI (Phase 9).

Heavy processing tasks that run in the background:
- Document processing
- OCR
- Embedding generation
- Indexing
- Report generation
"""
import os
import json
import datetime
from typing import Dict, Any

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()

from worker.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3)
def process_document_task(self, project: str, file_path: str, filename: str,
                          discipline: str = "", category: str = ""):
    """Compatibility entry point: enqueue into the canonical app-owned runner.

    Celery never imports main, mutates FAISS, or invents readiness independently.
    The application must run against the same data directory.
    """
    import db
    from services.jobs import JobQueue
    queue = JobQueue(db.DATA_DIR)
    job_id = queue.enqueue('document', file_path, dict(project=project,
        save_path=file_path, filename=filename, disc=discipline, category=category,
        folder_id=db.document_folder_id_for_path(project,file_path)))
    return {'status':'queued','job_id':job_id,'filename':filename}


@celery_app.task(bind=True, max_retries=2)
def ocr_task(self, image_path: str, source_doc: str = ""):
    """Run OCR on an image."""
    try:
        from engines.ocr_engine import get_ocr_engine
        engine = get_ocr_engine()
        result = engine.recognize(image_path, source_doc=source_doc)
        return {
            "status": "completed",
            "text": result.full_text,
            "confidence": result.average_confidence,
        }
    except Exception as exc:
        logger.error("OCR failed: {} - {}", image_path, exc)
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(bind=True, max_retries=2)
def embed_documents_task(self, texts: list, collection: str = "default"):
    """Generate embeddings for documents."""
    try:
        import local_embed
        embedder = local_embed.LocalOllamaEmbeddings()
        embeddings = embedder.embed_documents(texts)
        return {"status": "completed", "count": len(embeddings)}
    except Exception as exc:
        logger.error("Embedding failed: {}", exc)
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(bind=True, max_retries=2)
def generate_report_task(self, report_type: str, project_id: str, format: str = "pdf"):
    """Generate a report in the background."""
    try:
        from intelligence.reports import get_report_engine
        engine = get_report_engine()

        # Gather data
        from intelligence.validation import get_validation_engine
        validation = get_validation_engine()
        findings = list(validation._findings.values())
        findings = [f.__dict__ if hasattr(f, '__dict__') else f for f in findings]

        if report_type == "compliance":
            report = engine.generate_compliance_report(project_id, findings)
        elif report_type == "issue_register":
            report = engine.generate_issue_register(project_id, findings)
        else:
            report = engine.generate_compliance_report(project_id, findings)

        # Export
        output_dir = os.path.join(__import__("db").DATA_DIR, "reports", project_id)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{report.report_id}.{format}")
        engine.export(report, output_path, format)

        return {"status": "completed", "report_id": report.report_id, "path": output_path}

    except Exception as exc:
        logger.error("Report generation failed: {}", exc)
        raise self.retry(exc=exc, countdown=60)
