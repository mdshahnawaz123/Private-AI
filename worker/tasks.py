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
    """
    Process a document in the background.
    Deep extraction, entity extraction, indexing.
    """
    try:
        logger.info("Processing document: {} (project: {})", filename, project)

        # Import here to avoid circular imports
        import extract
        import vision
        import cad
        from knowledge.extraction import index_structured_entities

        ext = os.path.splitext(file_path)[-1].lower()
        combined = ""
        meta = {"type": "other"}

        if ext == ".pdf":
            combined, meta = extract.extract_pdf(
                file_path, vision_fn=vision.describe_image,
                render_dir=file_path + "_pages", deep=True
            )
        elif ext in (".xlsx", ".xls"):
            combined, meta = extract.extract_excel(file_path)
        elif ext == ".docx":
            combined, meta = extract.extract_docx(file_path)
        elif cad.is_cad(file_path):
            data, imgs = cad.ingest(file_path, file_path + "_render")
            combined = data or ""
            meta = {"type": "cad", "data": data, "views": []}
        elif vision.is_image(file_path):
            combined = vision.describe_image(file_path) or ""
            meta = {"type": "image", "vision": combined}

        # Save extraction
        meta["filename"] = filename
        meta["category"] = category
        extract.save_json(file_path + ".index.json", meta)

        with open(file_path + ".extracted.txt", "w", encoding="utf-8") as f:
            f.write(combined or "")

        # Index structured entities
        counts = index_structured_entities(project, filename, meta)

        # Update status
        import db
        chunks_n = counts.get("requirements", 0) + counts.get("evidence", 0)
        db.update_document_status(project, filename, max(chunks_n, 1), "ready")

        logger.info("Document processed: {} ({})", filename, counts)
        return {"status": "completed", "filename": filename, "counts": counts}

    except Exception as exc:
        logger.error("Document processing failed: {} - {}", filename, exc)
        # Update status to failed
        try:
            import db
            db.update_document_status(project, filename, 0, "failed")
        except Exception:
            pass
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


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
        output_dir = os.path.join("data", "reports", project_id)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{report.report_id}.{format}")
        engine.export(report, output_path, format)

        return {"status": "completed", "report_id": report.report_id, "path": output_path}

    except Exception as exc:
        logger.error("Report generation failed: {}", exc)
        raise self.retry(exc=exc, countdown=60)
