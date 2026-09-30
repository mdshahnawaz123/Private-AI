"""
Layout Engine for Expo Design AI (Phase 5).

Document layout detection — separate from OCR.
Detects: tables, figures, columns, headers, footers, text blocks.

Supports multiple backends:
- PP-DocLayout (preferred, local)
- Vision model (fallback)
"""
import os
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


class LayoutBlockType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"
    IMAGE = "image"
    HEADER = "header"
    FOOTER = "footer"
    COLUMN = "column"
    TITLE = "title"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    PAGE_NUMBER = "page_number"


@dataclass
class LayoutBlock:
    """A detected layout block."""
    block_type: LayoutBlockType
    bounding_box: Dict[str, float] = field(default_factory=dict)  # {x, y, w, h}
    content: str = ""
    confidence: float = 0.0
    page: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LayoutPageResult:
    """Layout detection results for a single page."""
    page_number: int
    blocks: List[LayoutBlock] = field(default_factory=list)
    has_table: bool = False
    has_figure: bool = False
    has_image: bool = False
    column_count: int = 1


class LayoutEngine:
    """
    Document layout detection engine.
    Detects structural elements beyond plain text.
    """

    def __init__(self):
        self._pp_available = False
        self._vision_available = False
        self._check_backends()

    def _check_backends(self):
        """Check which layout backends are available."""
        try:
            from paddleocr import PPStructure  # noqa: F401
            self._pp_available = True
            logger.info("PP-DocLayout available")
        except ImportError:
            logger.info("PP-DocLayout not available")

        self._vision_available = True
        logger.info("Vision model layout detection available")

    def is_available(self) -> bool:
        """Check if any layout backend is available."""
        return self._pp_available or self._vision_available

    def get_backend(self) -> str:
        """Get the best available backend name."""
        if self._pp_available:
            return "pp-doclayout"
        elif self._vision_available:
            return "vision"
        return "none"

    def detect(self, image_path: str, page: int = None) -> LayoutPageResult:
        """
        Detect layout in a document image.
        Returns LayoutPageResult with detected blocks.
        """
        if self._pp_available:
            return self._detect_pp(image_path, page)
        elif self._vision_available:
            return self._detect_vision(image_path, page)
        else:
            logger.error("No layout backend available")
            return LayoutPageResult(page_number=page or 0)

    def _detect_pp(self, image_path: str, page: int) -> LayoutPageResult:
        """Detect layout using PP-DocLayout."""
        try:
            from paddleocr import PPStructure
            engine = PPStructure(show_log=False)
            result = engine(image_path)

            blocks = []
            has_table = False
            has_figure = False
            has_image = False

            for region in result:
                region_type = region.get('type', 'unknown')
                bbox = region.get('bbox', [0, 0, 0, 0])

                block_type = LayoutBlockType.TEXT
                if region_type == 'table':
                    block_type = LayoutBlockType.TABLE
                    has_table = True
                elif region_type == 'figure':
                    block_type = LayoutBlockType.FIGURE
                    has_figure = True
                elif region_type == 'image':
                    block_type = LayoutBlockType.IMAGE
                    has_image = True
                elif region_type == 'header':
                    block_type = LayoutBlockType.HEADER
                elif region_type == 'footer':
                    block_type = LayoutBlockType.FOOTER
                elif region_type == 'title':
                    block_type = LayoutBlockType.TITLE
                elif region_type == 'caption':
                    block_type = LayoutBlockType.CAPTION
                elif region_type == 'footnote':
                    block_type = LayoutBlockType.FOOTNOTE
                elif region_type == 'page_number':
                    block_type = LayoutBlockType.PAGE_NUMBER

                blocks.append(LayoutBlock(
                    block_type=block_type,
                    bounding_box={
                        "x": bbox[0],
                        "y": bbox[1],
                        "w": bbox[2] - bbox[0],
                        "h": bbox[3] - bbox[1],
                    },
                    content=region.get('text', ''),
                    confidence=region.get('score', 0.0),
                    page=page,
                ))

            return LayoutPageResult(
                page_number=page or 0,
                blocks=blocks,
                has_table=has_table,
                has_figure=has_figure,
                has_image=has_image,
            )

        except Exception as e:
            logger.warning("PP-DocLayout failed: {}, falling back to vision", e)
            return self._detect_vision(image_path, page)

    def _detect_vision(self, image_path: str, page: int) -> LayoutPageResult:
        """Detect layout using vision model."""
        try:
            import vision
            text = vision.describe_image(image_path, instruction=(
                "Analyze the layout of this document page. Identify and list:\n"
                "1. Tables (describe location and content)\n"
                "2. Figures/diagrams (describe location and type)\n"
                "3. Images/photos (describe location)\n"
                "4. Headers and footers\n"
                "5. Column layout (single or multi-column)\n"
                "6. Any other structural elements\n\n"
                "Be specific about locations (top, bottom, left, right, center)."
            ))

            # Parse vision output into blocks (simplified)
            blocks = [LayoutBlock(
                block_type=LayoutBlockType.TEXT,
                content=text or "",
                confidence=0.6,
                page=page,
            )]

            return LayoutPageResult(
                page_number=page or 0,
                blocks=blocks,
            )

        except Exception as e:
            logger.error("Vision layout detection failed: {}", e)
            return LayoutPageResult(page_number=page or 0)

    def detect_batch(self, image_paths: List[str]) -> List[LayoutPageResult]:
        """Detect layout in multiple images."""
        results = []
        for i, path in enumerate(image_paths):
            result = self.detect(path, page=i + 1)
            results.append(result)
        return results

    def extract_tables(self, image_path: str, page: int = None) -> List[Dict[str, Any]]:
        """Extract tables from a document image."""
        result = self.detect(image_path, page)
        tables = []
        for block in result.blocks:
            if block.block_type == LayoutBlockType.TABLE:
                tables.append({
                    "bounding_box": block.bounding_box,
                    "content": block.content,
                    "page": block.page,
                    "confidence": block.confidence,
                })
        return tables

    def extract_figures(self, image_path: str, page: int = None) -> List[Dict[str, Any]]:
        """Extract figures from a document image."""
        result = self.detect(image_path, page)
        figures = []
        for block in result.blocks:
            if block.block_type in (LayoutBlockType.FIGURE, LayoutBlockType.IMAGE):
                figures.append({
                    "bounding_box": block.bounding_box,
                    "content": block.content,
                    "page": block.page,
                    "confidence": block.confidence,
                })
        return figures


# Singleton instance
_layout_engine = LayoutEngine()


def get_layout_engine() -> LayoutEngine:
    """Get the global layout engine instance."""
    return _layout_engine
