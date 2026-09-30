"""
Drawing Intelligence Engine for Expo Design AI (Phase 5).

Specialized engine for engineering drawings:
- Drawing comparison (two revisions)
- Dimension extraction
- Symbol detection
- Annotation/redline support
- Drawing-to-code validation preparation
"""
import os
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


@dataclass
class Dimension:
    """A dimension extracted from a drawing."""
    value: float
    unit: str
    dimension_type: str  # linear, angular, radial, diameter
    location: str = ""  # where on the drawing
    confidence: float = 0.0
    text: str = ""  # original text


@dataclass
class DrawingElement:
    """An element detected in a drawing."""
    element_type: str  # wall, door, window, column, beam, etc.
    location: Dict[str, float] = field(default_factory=dict)  # {x, y}
    dimensions: Dict[str, float] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


@dataclass
class DrawingComparisonResult:
    """Result of comparing two drawing revisions."""
    revision_a: str = ""
    revision_b: str = ""
    changes: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    total_changes: int = 0


class DrawingIntelligenceEngine:
    """
    Specialized engine for engineering drawing intelligence.
    """

    def __init__(self):
        self._ocr_engine = None
        self._layout_engine = None

    @property
    def ocr_engine(self):
        if self._ocr_engine is None:
            from engines.ocr_engine import get_ocr_engine
            self._ocr_engine = get_ocr_engine()
        return self._ocr_engine

    @property
    def layout_engine(self):
        if self._layout_engine is None:
            from engines.layout_engine import get_layout_engine
            self._layout_engine = get_layout_engine()
        return self._layout_engine

    def extract_dimensions(self, text: str) -> List[Dimension]:
        """
        Extract dimensions from drawing text.
        Looks for patterns like: 1200, 1200mm, 1.2m, Ø200, R500, etc.
        """
        dimensions = []

        # Linear dimensions: 1200, 1200mm, 1.2m
        linear_pattern = r'(\d+(?:\.\d+)?)\s*(mm|cm|m|in|ft)\b'
        for match in re.finditer(linear_pattern, text, re.IGNORECASE):
            value = float(match.group(1))
            unit = match.group(2).lower()
            dimensions.append(Dimension(
                value=value,
                unit=unit,
                dimension_type="linear",
                text=match.group(0),
                confidence=0.9,
            ))

        # Diameter: Ø200, D200, dia 200
        diameter_pattern = r'(?:Ø|D|dia\.?)\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)?'
        for match in re.finditer(diameter_pattern, text, re.IGNORECASE):
            value = float(match.group(1))
            unit = (match.group(2) or "mm").lower()
            dimensions.append(Dimension(
                value=value,
                unit=unit,
                dimension_type="diameter",
                text=match.group(0),
                confidence=0.85,
            ))

        # Radius: R500
        radius_pattern = r'R\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)?'
        for match in re.finditer(radius_pattern, text, re.IGNORECASE):
            value = float(match.group(1))
            unit = (match.group(2) or "mm").lower()
            dimensions.append(Dimension(
                value=value,
                unit=unit,
                dimension_type="radial",
                text=match.group(0),
                confidence=0.85,
            ))

        # Angular: 45°, 90°
        angular_pattern = r'(\d+(?:\.\d+)?)\s*°'
        for match in re.finditer(angular_pattern, text):
            value = float(match.group(1))
            dimensions.append(Dimension(
                value=value,
                unit="degrees",
                dimension_type="angular",
                text=match.group(0),
                confidence=0.9,
            ))

        logger.info("Extracted {} dimensions from drawing text", len(dimensions))
        return dimensions

    def detect_elements(self, text: str) -> List[DrawingElement]:
        """
        Detect drawing elements from text.
        Looks for common engineering symbols and labels.
        """
        elements = []

        # Door patterns: D1, D2, Door 1, etc.
        door_pattern = r'\bD(\d+)\b'
        for match in re.finditer(door_pattern, text):
            elements.append(DrawingElement(
                element_type="door",
                properties={"door_number": match.group(1)},
                confidence=0.8,
            ))

        # Window patterns: W1, W2, Window 1, etc.
        window_pattern = r'\bW(\d+)\b'
        for match in re.finditer(window_pattern, text):
            elements.append(DrawingElement(
                element_type="window",
                properties={"window_number": match.group(1)},
                confidence=0.8,
            ))

        # Room patterns: R1, R2, Room 1, etc.
        room_pattern = r'\bR(\d+)\b'
        for match in re.finditer(room_pattern, text):
            elements.append(DrawingElement(
                element_type="room",
                properties={"room_number": match.group(1)},
                confidence=0.7,
            ))

        # Level patterns: L1, L2, Level 1, etc.
        level_pattern = r'\bL(\d+)\b'
        for match in re.finditer(level_pattern, text):
            elements.append(DrawingElement(
                element_type="level",
                properties={"level_number": match.group(1)},
                confidence=0.7,
            ))

        # Grid patterns: A, B, C, 1, 2, 3
        grid_pattern = r'\b([A-Z])\b|\b(\d+)\b'
        for match in re.finditer(grid_pattern, text):
            elements.append(DrawingElement(
                element_type="grid",
                properties={"grid_reference": match.group(0)},
                confidence=0.5,
            ))

        logger.info("Detected {} elements from drawing text", len(elements))
        return elements

    def compare_drawings(self, text_a: str, text_b: str,
                         revision_a: str = "", revision_b: str = "") -> DrawingComparisonResult:
        """
        Compare two drawing revisions.
        Returns a list of changes between revisions.
        """
        changes = []

        # Extract dimensions from both
        dims_a = self.extract_dimensions(text_a)
        dims_b = self.extract_dimensions(text_b)

        # Compare dimensions
        dims_a_set = {(d.value, d.unit, d.dimension_type) for d in dims_a}
        dims_b_set = {(d.value, d.unit, d.dimension_type) for d in dims_b}

        added_dims = dims_b_set - dims_a_set
        removed_dims = dims_a_set - dims_b_set

        for dim in added_dims:
            changes.append({
                "type": "dimension_added",
                "value": dim[0],
                "unit": dim[1],
                "dimension_type": dim[2],
                "description": f"New dimension: {dim[0]} {dim[1]}",
            })

        for dim in removed_dims:
            changes.append({
                "type": "dimension_removed",
                "value": dim[0],
                "unit": dim[1],
                "dimension_type": dim[2],
                "description": f"Removed dimension: {dim[0]} {dim[1]}",
            })

        # Compare elements
        elems_a = self.detect_elements(text_a)
        elems_b = self.detect_elements(text_b)

        elems_a_set = {(e.element_type, e.properties.get("door_number", e.properties.get("window_number", ""))) for e in elems_a}
        elems_b_set = {(e.element_type, e.properties.get("door_number", e.properties.get("window_number", ""))) for e in elems_b}

        added_elems = elems_b_set - elems_a_set
        removed_elems = elems_a_set - elems_b_set

        for elem in added_elems:
            changes.append({
                "type": "element_added",
                "element_type": elem[0],
                "description": f"New {elem[0]}: {elem[1]}",
            })

        for elem in removed_elems:
            changes.append({
                "type": "element_removed",
                "element_type": elem[0],
                "description": f"Removed {elem[0]}: {elem[1]}",
            })

        # Text diff (simple word-level)
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        added_words = words_b - words_a
        removed_words = words_a - words_b

        if added_words:
            changes.append({
                "type": "text_added",
                "description": f"Added text: {', '.join(list(added_words)[:10])}",
            })

        if removed_words:
            changes.append({
                "type": "text_removed",
                "description": f"Removed text: {', '.join(list(removed_words)[:10])}",
            })

        summary = f"Found {len(changes)} changes between revisions {revision_a} and {revision_b}"

        return DrawingComparisonResult(
            revision_a=revision_a,
            revision_b=revision_b,
            changes=changes,
            summary=summary,
            total_changes=len(changes),
        )

    def analyze_drawing(self, image_path: str, ocr_text: str = "") -> Dict[str, Any]:
        """
        Comprehensive drawing analysis.
        Combines OCR, layout detection, and element detection.
        """
        result = {
            "image_path": image_path,
            "dimensions": [],
            "elements": [],
            "layout": None,
            "ocr_text": ocr_text,
        }

        # Extract dimensions from OCR text
        if ocr_text:
            result["dimensions"] = [
                {"value": d.value, "unit": d.unit, "type": d.dimension_type, "text": d.text}
                for d in self.extract_dimensions(ocr_text)
            ]
            result["elements"] = [
                {"type": e.element_type, "properties": e.properties}
                for e in self.detect_elements(ocr_text)
            ]

        # Layout detection
        try:
            layout = self.layout_engine.detect(image_path)
            result["layout"] = {
                "has_table": layout.has_table,
                "has_figure": layout.has_figure,
                "has_image": layout.has_image,
                "block_count": len(layout.blocks),
            }
        except Exception as e:
            logger.warning("Layout detection failed: {}", e)

        return result


# Singleton instance
_drawing_engine = DrawingIntelligenceEngine()


def get_drawing_engine() -> DrawingIntelligenceEngine:
    """Get the global drawing intelligence engine instance."""
    return _drawing_engine
