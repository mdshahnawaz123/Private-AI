"""
Admin Ingestion Pipeline for Expo Design AI (Phase 1).

Manages the full document lifecycle:
UPLOADED → PROCESSING → REVIEW_REQUIRED → VERIFIED → PUBLISHED

Key principles:
- Process once, retrieve many
- Never silently overwrite
- Provenance always
- Human verification for low-confidence
- Indexes rebuildable
"""
import os
import hashlib
import json
import datetime
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


class UploadTooLargeError(Exception):
    """Raised by save_upload_capped() when a file exceeds the configured
    max_upload_size_mb. Deliberately NOT a FastAPI HTTPException -- this
    module has no framework dependency -- callers translate it (main.py
    raises HTTPException(413, ...) on catching it)."""
    pass


def save_upload_capped(fileobj, save_path: str, max_bytes: int, chunk_size: int = 1024 * 1024) -> int:
    """Stream `fileobj` (anything with a .read(n) method -- an UploadFile's
    .file, or a plain file object in tests) to `save_path`, aborting and
    deleting the partial file if the total written exceeds `max_bytes`.

    Security fix: originally /upload and /chat/attachments wrote the whole
    file with shutil.copyfileobj() and never checked size at all, even
    though config.max_upload_size_mb existed -- any authenticated user could
    fill the disk with one oversized request. Pulled out of main.py into its
    own function here so it has no FastAPI coupling and can be unit-tested
    directly (importing main.py as a module has real side effects -- it
    initializes the live data/ directory at import time -- so it must never
    be imported from a test).

    Returns the number of bytes written. Raises UploadTooLargeError (and
    removes the partial file) if the limit is exceeded.
    """
    written = 0
    with open(save_path, "wb") as f:
        while True:
            chunk = fileobj.read(chunk_size)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                f.close()
                try:
                    os.remove(save_path)
                except Exception:
                    pass
                raise UploadTooLargeError(
                    f"File exceeds the maximum upload size ({max_bytes // (1024 * 1024)} MB).")
            f.write(chunk)
    return written


class DocumentState(str, Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    REVIEW_REQUIRED = "review_required"
    VERIFIED = "verified"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    STORED = "stored"  # Not AI-indexed (non-indexable file type)
    EXTRACTED = "extracted"  # Extraction done, indexing failed
    READY = "ready"  # Legacy status from Phase 0


class IngestionPipeline:
    """
    Manages document ingestion from upload to publish.
    Tracks state, quality, and provenance.
    """

    def __init__(self):
        self._quality_threshold = 0.6  # Minimum confidence for auto-publish

    def compute_sha256(self, file_path: str) -> str:
        """Compute SHA-256 hash of a file."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def check_duplicate(self, file_path: str, project: str) -> Optional[Dict[str, Any]]:
        """
        Check if a file with the same SHA-256 already exists in the project.
        Returns the existing document info if found, None otherwise.
        """
        import db
        file_hash = self.compute_sha256(file_path)
        docs = db.list_documents(project)
        for doc in docs:
            doc_path = doc.get("path", "")
            if doc_path and os.path.exists(doc_path):
                if self.compute_sha256(doc_path) == file_hash:
                    return {
                        "filename": doc["filename"],
                        "path": doc_path,
                        "status": doc.get("status", ""),
                        "uploaded_at": doc.get("uploaded_at", ""),
                    }
        return None

    def classify_file(self, filename: str, content_type: str = "") -> Dict[str, Any]:
        """
        Classify a file by type and content.
        Returns classification with category, discipline hint, and engine.
        """
        ext = os.path.splitext(filename)[-1].lower()

        # Category mapping
        category_map = {
            ".pdf": "Reports",
            ".docx": "Reports",
            ".doc": "Reports",
            ".txt": "Reports",
            ".rtf": "Reports",
            ".xlsx": "Schedules",
            ".xls": "Schedules",
            ".csv": "Schedules",
            ".dwg": "Drawings",
            ".dxf": "Drawings",
            ".rvt": "3D Models",
            ".rfa": "3D Models",
            ".nwd": "3D Models",
            ".nwc": "3D Models",
            ".ifc": "3D Models",
            ".skp": "3D Models",
            ".fbx": "3D Models",
            ".obj": "3D Models",
            ".glb": "3D Models",
            ".gltf": "3D Models",
            ".step": "3D Models",
            ".stp": "3D Models",
            ".iges": "3D Models",
            ".igs": "3D Models",
            ".png": "Images",
            ".jpg": "Images",
            ".jpeg": "Images",
            ".webp": "Images",
            ".bmp": "Images",
            ".tif": "Images",
            ".tiff": "Images",
            ".gif": "Images",
        }

        category = category_map.get(ext, "Other")

        # Discipline hint from filename
        import meta_parse
        meta = meta_parse.parse_drawing_meta(filename)
        discipline = meta.get("discipline_hint", "")

        # Engine selection
        engine = self._select_engine(ext, category)

        return {
            "category": category,
            "discipline": discipline,
            "engine": engine,
            "doctype": meta.get("doctype", ""),
            "revision": meta.get("revision", ""),
            "base_id": meta.get("base_id", ""),
        }

    def _select_engine(self, ext: str, category: str) -> str:
        """Select the appropriate processing engine."""
        if ext == ".pdf":
            return "pdf_engine"
        elif ext in (".docx", ".doc"):
            return "word_engine"
        elif ext in (".xlsx", ".xls", ".csv"):
            return "excel_engine"
        elif ext in (".dwg", ".dxf"):
            return "cad_engine"
        elif ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"):
            return "image_engine"
        elif ext in (".ifc", ".rvt", ".nwd", ".nwc"):
            return "bim_engine"
        else:
            return "none"

    def extract_structured_tables(self, project_id: str, filename: str,
                                  meta: Dict[str, Any]) -> int:
        """
        Extract structured tables from document metadata.
        Phase 2: Store each row as a structured record.
        """
        try:
            from knowledge.extraction import index_structured_tables, index_visual_structured_records
            count1 = index_structured_tables(project_id, filename, meta)
            count2 = index_visual_structured_records(project_id, filename, meta)
            return count1 + count2
        except Exception as e:
            logger.warning("Structured table extraction failed: {}", e)
            return 0

    def extract_quantities(self, project_id: str, filename: str,
                           meta: Dict[str, Any]) -> int:
        """
        Extract numeric quantities from document metadata.
        Phase 2: Store quantities as structured data.
        """
        try:
            from knowledge.extraction import index_quantities
            return index_quantities(project_id, filename, meta)
        except Exception as e:
            logger.warning("Quantities extraction failed: {}", e)
            return 0

    def quality_check(self, extraction_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run quality checks on extraction results.
        Returns quality score and flags for review.
        """
        score = 1.0
        flags = []

        # Check if extraction produced any content
        if not extraction_result.get("text") and not extraction_result.get("pages"):
            score -= 0.5
            flags.append("No text content extracted")

        # Check vision confidence
        vision_errors = extraction_result.get("vision_errors", 0)
        if vision_errors > 0:
            score -= 0.1 * min(vision_errors, 5)
            flags.append(f"{vision_errors} vision errors")

        # Check page count for PDFs
        if extraction_result.get("type") == "pdf":
            pages = extraction_result.get("pages", [])
            if not pages:
                score -= 0.3
                flags.append("No pages extracted from PDF")
            elif len(pages) == 1 and not pages[0].get("text"):
                score -= 0.2
                flags.append("Single page with no text")

        # Check for [illegible] markers (vision uncertainty)
        text = extraction_result.get("text", "")
        illegible_count = text.count("[illegible]")
        if illegible_count > 0:
            score -= 0.05 * min(illegible_count, 10)
            flags.append(f"{illegible_count} illegible markers")

        # Clamp score
        score = max(0.0, min(1.0, score))

        # Determine if review is required
        needs_review = score < self._quality_threshold

        return {
            "score": score,
            "flags": flags,
            "needs_review": needs_review,
            "can_auto_publish": score >= self._quality_threshold,
        }

    def get_next_state(self, current_state: str, quality_score: float) -> str:
        """Determine the next document state based on quality."""
        if current_state == DocumentState.UPLOADED:
            return DocumentState.PROCESSING
        elif current_state == DocumentState.PROCESSING:
            if quality_score >= self._quality_threshold:
                return DocumentState.VERIFIED
            else:
                return DocumentState.REVIEW_REQUIRED
        elif current_state == DocumentState.REVIEW_REQUIRED:
            return DocumentState.VERIFIED
        elif current_state == DocumentState.VERIFIED:
            return DocumentState.PUBLISHED
        return current_state

    def create_version_info(self, filename: str, revision: str = "") -> Dict[str, Any]:
        """Create version information for a document."""
        import meta_parse
        meta = meta_parse.parse_drawing_meta(filename)
        return {
            "base_id": meta.get("base_id", ""),
            "revision": revision or meta.get("revision", ""),
            "version": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "filename": filename,
        }


# Singleton instance
_pipeline = IngestionPipeline()


def get_pipeline() -> IngestionPipeline:
    """Get the global ingestion pipeline instance."""
    return _pipeline
