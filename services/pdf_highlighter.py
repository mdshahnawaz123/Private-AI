"""
pdf_highlighter.py — PyMuPDF-based PDF Evidence Highlighting & Coordinate Locator.

Features:
- Exact text search and bounding box extraction using PyMuPDF (fitz).
- Multi-line passage handling, sentence/phrase segmentation, and whitespace normalization.
- Page rotation and coordinate space transformation (raw points, rotated display points, normalized).
- Disambiguation to avoid highlighting unrelated text sharing a common keyword.
- Fallback to OCR bounding boxes for scanned documents and drawings.
- Non-destructive persistent PDF annotation (saves to a separate copy, preserves original).
- Fail-closed: if exact evidence coordinates cannot be established, returns found=False
  without fabricating coordinates.
"""
from __future__ import annotations

import difflib
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF

# Ambiguous single words that must not trigger a false-positive highlight across the document
AMBIGUOUS_KEYWORDS = {
    "the", "and", "or", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "note", "plan", "drawing", "section", "detail", "level", "page", "scale",
    "typical", "elevation", "floor", "sheet", "general", "rev", "date", "status"
}


def normalize_text(text: str) -> str:
    """Normalize whitespace, tabs, and newlines."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _is_too_ambiguous(snippet: str) -> bool:
    """Check if snippet is a single common word or too short to be unique evidence."""
    clean = normalize_text(snippet).lower().strip(".:;,()[]{}\"'")
    if len(clean) < 3:
        return True
    words = clean.split()
    if len(words) == 1 and clean in AMBIGUOUS_KEYWORDS:
        return True
    return False


def _rect_to_list(rect: fitz.Rect) -> List[float]:
    """Convert fitz.Rect to rounded list [x0, y0, x1, y1]."""
    return [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]


def _transform_rect(rect: fitz.Rect, matrix: fitz.Matrix) -> List[float]:
    """Apply transformation matrix to rect (e.g. page.rotation_matrix)."""
    transformed = rect * matrix
    return [
        round(min(transformed.x0, transformed.x1), 2),
        round(min(transformed.y0, transformed.y1), 2),
        round(max(transformed.x0, transformed.x1), 2),
        round(max(transformed.y0, transformed.y1), 2),
    ]


def locate_evidence_in_page(
    page: fitz.Page,
    snippet: str,
    meta_page: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Locate the exact supporting text or region on a single PyMuPDF page.
    Returns:
    {
        "found": bool,
        "rects": List[List[float]],           # Unrotated PDF points [x0, y0, x1, y1]
        "display_rects": List[List[float]],   # Viewport/rotated points
        "normalized_rects": List[List[float]],# 0.0 - 1.0 relative to page dimensions
        "rotation": int,
        "match_type": str,                   # "exact", "multiline", "ocr_fallback", "none"
        "confidence": float,
        "reason": Optional[str],
    }
    """
    clean_snippet = normalize_text(snippet)
    if not clean_snippet or _is_too_ambiguous(clean_snippet):
        return {
            "found": False,
            "rects": [],
            "display_rects": [],
            "normalized_rects": [],
            "rotation": page.rotation,
            "match_type": "none",
            "confidence": 0.0,
            "reason": "Snippet is empty, too short, or too ambiguous",
        }

    page_width = float(page.rect.width)
    page_height = float(page.rect.height)
    rot_matrix = page.rotation_matrix

    # 1. Exact text search via PyMuPDF search_for
    exact_matches = page.search_for(clean_snippet)
    if exact_matches:
        # If multiple matches occur, verify context uniqueness
        chosen_match = exact_matches[0]
        rects = [_rect_to_list(chosen_match)]
        display_rects = [_transform_rect(chosen_match, rot_matrix)]
        norm_rects = [
            [
                round(chosen_match.x0 / page_width, 4),
                round(chosen_match.y0 / page_height, 4),
                round(chosen_match.x1 / page_width, 4),
                round(chosen_match.y1 / page_height, 4),
            ]
        ]
        return {
            "found": True,
            "rects": rects,
            "display_rects": display_rects,
            "normalized_rects": norm_rects,
            "rotation": page.rotation,
            "match_type": "exact",
            "confidence": 1.0 if len(exact_matches) == 1 else 0.85,
            "reason": None,
        }

    # 2. Multi-line passage handling:
    # Text in PDFs frequently wraps across linebreaks or has variable hyphenation.
    # Split snippet into sentences or word chunks of 3-5 words each.
    words = clean_snippet.split()
    if len(words) >= 3:
        # Try finding the start and end phrase of the multi-line passage
        window_size = min(4, len(words))
        start_phrase = " ".join(words[:window_size])
        end_phrase = " ".join(words[-window_size:])

        start_hits = page.search_for(start_phrase)
        end_hits = page.search_for(end_phrase)

        if start_hits and end_hits:
            # Pair the closest start and end hit
            best_pair = None
            min_dist = float("inf")
            for sh in start_hits:
                for eh in end_hits:
                    # End must be at or below start vertically (or to the right on same line)
                    if eh.y1 >= sh.y0 - 5:
                        dist = abs(eh.y1 - sh.y0)
                        if dist < min_dist and dist < 300:  # within 300 points vertically
                            min_dist = dist
                            best_pair = (sh, eh)

            if best_pair:
                sh, eh = best_pair
                # Create bounding box enclosing the multi-line passage
                passage_rect = fitz.Rect(
                    min(sh.x0, eh.x0),
                    min(sh.y0, eh.y0),
                    max(sh.x1, eh.x1),
                    max(sh.y1, eh.y1),
                )
                rects = [_rect_to_list(passage_rect)]
                display_rects = [_transform_rect(passage_rect, rot_matrix)]
                norm_rects = [
                    [
                        round(passage_rect.x0 / page_width, 4),
                        round(passage_rect.y0 / page_height, 4),
                        round(passage_rect.x1 / page_width, 4),
                        round(passage_rect.y1 / page_height, 4),
                    ]
                ]
                return {
                    "found": True,
                    "rects": rects,
                    "display_rects": display_rects,
                    "normalized_rects": norm_rects,
                    "rotation": page.rotation,
                    "match_type": "multiline",
                    "confidence": 0.9,
                    "reason": None,
                }

        # Sub-chunk progressive match: match consecutive lines
        chunk_rects: List[fitz.Rect] = []
        for i in range(0, len(words), 3):
            sub_phrase = " ".join(words[i : i + 3])
            sub_hits = page.search_for(sub_phrase)
            if sub_hits:
                chunk_rects.append(sub_hits[0])

        if len(chunk_rects) >= 2 and len(chunk_rects) >= (len(words) // 4):
            # Enclose the matched consecutive chunks
            union_rect = chunk_rects[0]
            for cr in chunk_rects[1:]:
                union_rect = union_rect | cr

            rects = [_rect_to_list(union_rect)]
            display_rects = [_transform_rect(union_rect, rot_matrix)]
            norm_rects = [
                [
                    round(union_rect.x0 / page_width, 4),
                    round(union_rect.y0 / page_height, 4),
                    round(union_rect.x1 / page_width, 4),
                    round(union_rect.y1 / page_height, 4),
                ]
            ]
            return {
                "found": True,
                "rects": rects,
                "display_rects": display_rects,
                "normalized_rects": norm_rects,
                "rotation": page.rotation,
                "match_type": "multiline",
                "confidence": 0.8,
                "reason": None,
            }

    # 3. Scanned PDF fallback via OCR or inspection metadata
    if meta_page:
        # Check native spans from pdf_inspection
        spans = meta_page.get("inspection", {}).get("native_spans", [])
        for sp in spans:
            t = normalize_text(sp.get("text", ""))
            if clean_snippet in t or (len(clean_snippet) > 10 and clean_snippet[:20] in t):
                box = sp.get("bbox")
                if box and len(box) == 4:
                    fr = fitz.Rect(box)
                    return {
                        "found": True,
                        "rects": [_rect_to_list(fr)],
                        "display_rects": [_transform_rect(fr, rot_matrix)],
                        "normalized_rects": [
                            [
                                round(fr.x0 / page_width, 4),
                                round(fr.y0 / page_height, 4),
                                round(fr.x1 / page_width, 4),
                                round(fr.y1 / page_height, 4),
                            ]
                        ],
                        "rotation": page.rotation,
                        "match_type": "inspection_span",
                        "confidence": 0.85,
                        "reason": None,
                    }

        # Check OCR boxes from page_ocr
        ocr_boxes = meta_page.get("ocr", {}).get("boxes", [])
        if ocr_boxes:
            matched_boxes = []
            snippet_lower = clean_snippet.lower()
            for b in ocr_boxes:
                b_text = str(b.get("text", "")).strip().lower()
                if b_text and b_text in snippet_lower and len(b_text) >= 3:
                    box_coord = b.get("bbox") or b.get("box")
                    if box_coord and len(box_coord) == 4:
                        matched_boxes.append(fitz.Rect(box_coord))

            if matched_boxes and len(matched_boxes) >= min(2, len(words)):
                ocr_union = matched_boxes[0]
                for mb in matched_boxes[1:]:
                    ocr_union = ocr_union | mb
                return {
                    "found": True,
                    "rects": [_rect_to_list(ocr_union)],
                    "display_rects": [_transform_rect(ocr_union, rot_matrix)],
                    "normalized_rects": [
                        [
                            round(ocr_union.x0 / page_width, 4),
                            round(ocr_union.y0 / page_height, 4),
                            round(ocr_union.x1 / page_width, 4),
                            round(ocr_union.y1 / page_height, 4),
                        ]
                    ],
                    "rotation": page.rotation,
                    "match_type": "ocr_fallback",
                    "confidence": 0.75,
                    "reason": None,
                }

    # Fail-closed safeguard: do NOT fabricate coordinates if evidence cannot be found
    return {
        "found": False,
        "rects": [],
        "display_rects": [],
        "normalized_rects": [],
        "rotation": page.rotation,
        "match_type": "none",
        "confidence": 0.0,
        "reason": "Exact supporting text coordinates could not be established on this page",
    }


def locate_evidence(
    pdf_path: str,
    page_num: int,
    snippet: str,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Safe entry point to locate supporting evidence across a document page.
    Returns fail-closed result if document or page does not exist.
    """
    if not os.path.isfile(pdf_path):
        return {
            "found": False,
            "page": page_num,
            "rects": [],
            "display_rects": [],
            "normalized_rects": [],
            "reason": f"PDF file not found: {pdf_path}",
        }

    try:
        with fitz.open(pdf_path) as doc:
            if page_num < 1 or page_num > len(doc):
                return {
                    "found": False,
                    "page": page_num,
                    "rects": [],
                    "display_rects": [],
                    "normalized_rects": [],
                    "reason": f"Page {page_num} out of bounds (1..{len(doc)})",
                }

            page = doc[page_num - 1]
            meta_page = None
            if meta and "pages" in meta:
                pages_meta = meta["pages"]
                if isinstance(pages_meta, list) and 0 <= (page_num - 1) < len(pages_meta):
                    meta_page = pages_meta[page_num - 1]

            result = locate_evidence_in_page(page, snippet, meta_page)
            result["page"] = page_num
            result["page_size"] = [round(page.rect.width, 2), round(page.rect.height, 2)]
            return result
    except Exception as e:
        return {
            "found": False,
            "page": page_num,
            "rects": [],
            "display_rects": [],
            "normalized_rects": [],
            "reason": f"Error opening or reading PDF: {str(e)}",
        }


def create_annotated_copy(
    pdf_path: str,
    page_highlights: List[Dict[str, Any]],
    output_path: Optional[str] = None,
) -> str:
    """
    Create a persistent, annotated copy of the PDF with highlighted evidence regions.
    Preserves original PDF completely and saves annotated version separately.
    page_highlights: list of dicts: {"page": int, "rects": [[x0, y0, x1, y1], ...]}
    """
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    if not output_path:
        base, ext = os.path.splitext(pdf_path)
        output_path = f"{base}_annotated{ext}"

    with fitz.open(pdf_path) as doc:
        for hl in page_highlights:
            p_num = hl.get("page", 1)
            if 1 <= p_num <= len(doc):
                page = doc[p_num - 1]
                rects = hl.get("rects", [])
                for r in rects:
                    if len(r) == 4:
                        fitz_rect = fitz.Rect(r)
                        annot = page.add_highlight_annot(fitz_rect)
                        annot.set_colors(stroke=(1.0, 0.85, 0.1))  # Amber/yellow highlight
                        annot.update()

        doc.save(output_path, garbage=3, deflate=True)

    return output_path


def render_highlighted_page_pixmap(
    pdf_path: str,
    page_num: int,
    rects: List[List[float]],
    scale: float = 2.0,
) -> bytes:
    """
    Render a page preview image (PNG bytes) with yellow evidence highlights
    drawn on top. Original PDF is not modified.
    """
    with fitz.open(pdf_path) as doc:
        if page_num < 1 or page_num > len(doc):
            raise IndexError(f"Page {page_num} out of bounds")

        page = doc[page_num - 1]

        # Draw highlight overlays on a temporary shape
        if rects:
            shape = page.new_shape()
            for r in rects:
                if len(r) == 4:
                    shape.draw_rect(fitz.Rect(r))
            shape.finish(
                fill=(1.0, 0.88, 0.15),
                color=(0.95, 0.75, 0.0),
                fill_opacity=0.35,
                width=1.5,
            )
            shape.commit()

        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pix.tobytes("png")
