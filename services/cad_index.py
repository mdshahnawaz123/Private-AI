"""Make drawings saved inside the app searchable by the AI (2026-10-22).

Drawings uploaded through the normal upload are queued for the CAD reader, which
extracts layers, text, title block and dimensions so chat can answer about them. Drawings
created or edited inside the app (CADCraft save, the AI "cad_draft" tool) were only
recorded in the database and never read, so chat refused them ("not ready for
questions"). These helpers put them through the same durable ingestion queue.
"""
import os

from loguru import logger

import db


def queue_cad_indexing(project, path, filename, folder_id=None, discipline="Architectural"):
    """Mark the drawing as processing and queue it for the normal document pipeline."""
    try:
        from services.jobs import JobQueue
        db.update_document_status(project, filename, 0, "processing")
        JobQueue(db.DATA_DIR).enqueue("document", path, dict(project=project, save_path=path, filename=filename,
                                                            disc=discipline, category="Drawings", folder_id=folder_id))
        return True
    except Exception as e:
        logger.warning("Could not queue drawing {} for AI indexing: {}", filename, e)
        return False


def backfill_unindexed_drawings():
    """At startup: queue drawings that exist on disk but were never read (no saved extraction)."""
    n = 0
    try:
        with db.SessionLocal() as s:
            rows = (s.query(db.Document, db.Project.name).join(db.Project)
                    .filter(db.Document.status.in_(("ready", "review_required", "stored", "ready_with_warnings"))).all())
            todo = [(p, d.path, d.filename, d.folder_id) for d, p in rows
                    if d.path and d.path.lower().endswith((".dxf", ".dwg")) and os.path.isfile(d.path)
                    and not os.path.isfile(d.path + ".index.json")]
        for p, path, fn, fid in todo:
            if queue_cad_indexing(p, path, fn, fid):
                n += 1
    except Exception as e:
        logger.warning("Drawing backfill skipped: {}", e)
    if n:
        logger.info("Queued {} unindexed drawing(s) for AI indexing", n)
    return n
