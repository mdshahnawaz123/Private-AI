"""
Document-Adaptive Ingestion Router for Expo Design AI.
Inspects incoming files and routes them to the optimal specialized engine:
- UniversalDrawingEngine: for CAD (.dwg, .dxf) and large-format engineering drawing sheets.
- LayoutTableEngine: for dense multi-table data sheets and schedules.
- StructuredDocEngine: for multi-page technical reports and tabular forms (Meeting Minutes/ROMs).
"""
import os
import re
from typing import Dict, Any, Optional

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


class DocumentType:
    ENGINEERING_DRAWING = "ENGINEERING_DRAWING"
    DENSE_TABLE_SHEET = "DENSE_TABLE_SHEET"
    STRUCTURED_REPORT_OR_FORM = "STRUCTURED_REPORT_OR_FORM"
    BIM_MODEL = "BIM_MODEL"
    OTHER = "OTHER"


class DocumentRouter:
    """
    Classifies documents dynamically based on extension, geometry, and layout signals.
    """

    def classify_document(self, file_path: str, meta: Optional[Dict[str, Any]] = None) -> str:
        ext = os.path.splitext(file_path or "")[-1].lower()

        if ext in (".dwg", ".dxf"):
            return DocumentType.ENGINEERING_DRAWING

        if ext in (".ifc", ".rvt", ".nwd", ".nwc"):
            return DocumentType.BIM_MODEL

        if ext in (".xlsx", ".xls", ".csv"):
            return DocumentType.DENSE_TABLE_SHEET

        if ext == ".pdf":
            if meta is not None and "pages" in meta:
                pages = meta.get("pages", [])
                page_count = len(pages)
                # Check for drawing schema
                if any(p.get("drawing_schema", {}).get("is_drawing") for p in pages):
                    return DocumentType.ENGINEERING_DRAWING

                # Check for dense table count
                total_tables = sum(p.get("table_count", 0) for p in pages)
                if page_count <= 2 and total_tables >= 4:
                    return DocumentType.DENSE_TABLE_SHEET

                return DocumentType.STRUCTURED_REPORT_OR_FORM

            # If no meta, inspect PDF geometry directly
            try:
                import fitz
                with fitz.open(file_path) as doc:
                    if len(doc) > 0:
                        first_page = doc[0]
                        w, h = first_page.rect.width, first_page.rect.height
                        # Large format canvas (A0/A1 typically > 1200 points)
                        if w > 1200 or h > 1200:
                            return DocumentType.ENGINEERING_DRAWING
                        
                        txt = first_page.get_text()[:2000]
                        if re.search(r'\b(Drawing\s+No|Scale\s*@\s*A[0-4]|DO\s+NOT\s+SCALE|STORMWATER|STRUCTURAL\s+PLAN)\b', txt, re.I):
                            return DocumentType.ENGINEERING_DRAWING

                        if len(doc) <= 2:
                            tabs = first_page.find_tables()
                            if getattr(tabs, "tables", None) and len(tabs.tables) >= 4:
                                return DocumentType.DENSE_TABLE_SHEET

                        return DocumentType.STRUCTURED_REPORT_OR_FORM
            except Exception as e:
                logger.warning("Router direct PDF inspection failed: {}", e)

        return DocumentType.STRUCTURED_REPORT_OR_FORM


_document_router = None

def get_document_router() -> DocumentRouter:
    global _document_router
    if _document_router is None:
        _document_router = DocumentRouter()
    return _document_router
