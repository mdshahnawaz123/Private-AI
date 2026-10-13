"""
Layout Table Engine for Expo Design AI.
Specialized engine for dense multi-table engineering data sheets and schedules.
Provides table boundary segmentation, header inheritance, and self-contained structured serialization.
"""
import re
from typing import Dict, Any, List, Optional, Tuple

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


class LayoutTableEngine:
    """
    Extracts and normalizes multi-table layouts with header inheritance.
    Ensures that when text is cut into chunks, no row loses its table name, column headers, or units.
    """

    def process_tables(self, tables_text: str, page_text: str = "") -> Dict[str, Any]:
        """
        Parse raw table strings (markdown pipe tables or text tables) into header-inherited structured records.
        """
        result = {
            "tables": {},
            "record_count": 0,
            "header_inherited_markdown": ""
        }

        if not tables_text and not page_text:
            return result

        combined = (tables_text or "") + "\n\n" + (page_text or "")
        
        # Split into distinct tables by markdown table blocks or section headings
        lines = combined.splitlines()
        current_title = "GENERAL TABLE"
        current_headers: List[str] = []
        table_records: Dict[str, List[Dict[str, Any]]] = {}
        inherited_lines: List[str] = []

        in_table = False
        row_index = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                in_table = False
                continue

            # Detect table title or heading
            if stripped.startswith("#") or (stripped.isupper() and len(stripped) < 60 and not stripped.startswith("|")):
                title_clean = stripped.lstrip("#").strip()
                if any(w in title_clean for w in ["TABLE", "BREAKDOWN", "SUMMARY", "CALCULATION", "MATRIX", "SCHEDULE", "STATEMENT"]):
                    current_title = title_clean
                    current_headers = []
                    in_table = False
                    continue

            # Detect markdown pipe table
            if stripped.startswith("|") and stripped.endswith("|"):
                cells = [c.strip() for c in stripped[1:-1].split("|")]
                # Header separator line (e.g. |---|---|)
                if all(re.match(r'^:?-+:?$', c) for c in cells if c):
                    continue

                if not current_headers or not in_table:
                    # Treat first row as column headers
                    current_headers = cells
                    in_table = True
                    row_index = 0
                    continue

                # Data row
                row_dict = {}
                row_label = cells[0] if cells else f"Row {row_index}"
                for idx, cell in enumerate(cells):
                    header = current_headers[idx] if idx < len(current_headers) else f"Col_{idx}"
                    if header:
                        row_dict[header] = cell

                table_records.setdefault(current_title, []).append({
                    "row_label": row_label,
                    "cells": row_dict
                })

                # Format as self-contained inherited row sentence
                cell_strs = [f"{k}: {v}" for k, v in row_dict.items() if v and k != row_label]
                if cell_strs:
                    inherited_lines.append(f"[{current_title}] {row_label} -> " + " | ".join(cell_strs))
                row_index += 1

        # Also extract native key-value pairs from data sheet summaries if present in text
        summary_metrics = [
            ("Plot Area", r'Plot\s+Area\s*[:\s]+([\d,.]+\s*(?:sq\.?m\.?|sq\.?ft\.?)?)'),
            ("GFA Allowed", r'GFA\s+Allowed\s*[:\s]+([\d,.]+\s*(?:sq\.?m\.?|sq\.?ft\.?)?)'),
            ("GFA Proposed", r'GFA\s+Proposed\s*[:\s]+([\d,.]+\s*(?:sq\.?m\.?|sq\.?ft\.?)?)'),
            ("FAR Allowed", r'FAR\s+Allowed\s*[:\s]+([\d.]+)'),
            ("FAR Proposed", r'FAR\s+Proposed\s*[:\s]+([\d.]+)'),
            ("BUA Proposed", r'BUA\s+Proposed\s*[:\s]+([\d,.]+\s*(?:sq\.?m\.?|sq\.?ft\.?)?)'),
            ("Residential Units", r'Residential\s+Units\s*[:\s]+(\d+[\d,.]*)'),
            ("Total Parking", r'Total\s+Parking\s*[:\s]+(?:Required\s*[:=]\s*(\d+))?[,\s]*(?:Proposed\s*[:=]\s*(\d+))?'),
            ("Passenger Lifts", r'Passenger\s+Lifts?\s*[:\s]+(?:Required\s*[:=]\s*(\d+))?[,\s]*(?:Proposed\s*[:=]\s*(\d+))?'),
            ("Bicycle Racks", r'Bicycle\s+Racks?\s*[:\s]+(?:Required\s*[:=]\s*(\d+))?[,\s]*(?:Proposed\s*[:=]\s*(\d+))?')
        ]

        for label, pat in summary_metrics:
            m = re.search(pat, combined, re.I)
            if m:
                val = " / ".join(v for v in m.groups() if v)
                inherited_lines.append(f"[SUMMARY METRIC] {label}: {val}")

        result["tables"] = table_records
        result["record_count"] = sum(len(rows) for rows in table_records.values())
        result["header_inherited_markdown"] = "\n".join(inherited_lines)
        return result


_layout_table_engine = None

def get_layout_table_engine() -> LayoutTableEngine:
    global _layout_table_engine
    if _layout_table_engine is None:
        _layout_table_engine = LayoutTableEngine()
    return _layout_table_engine
