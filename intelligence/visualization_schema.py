"""
visualization_schema.py — Strict schema validation for Chart Visualizations
and PDF Evidence References.

Defines schemas and fail-closed validators for:
1. Chart Visualizations: pie, donut, bar, line, stacked_bar.
2. PDF Evidence References: document ID, filename, page, coordinates, snippet.

Ensures:
- Valid types, labels, numeric values, and dimensions.
- No invented or unverified model data.
- Deterministic validation before any data reaches the UI.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple, Union

VALID_CHART_TYPES = {"pie", "donut", "bar", "line", "stacked_bar"}

# Regex for extracting embedded chart JSON codeblocks: ```chart or ```json
_CHART_BLOCK_RX = re.compile(
    r"```(?:chart|json)\s*(\{[\s\S]*?\})\s*```",
    re.IGNORECASE,
)


def _is_finite_number(val: Any) -> bool:
    """Check if value is an int or float that is not NaN or infinite."""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return not (math.isnan(val) or math.isinf(val))
    return False


def validate_chart_spec(raw: Any) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Validate a chart specification dictionary against the strict chart schema.
    Returns (is_valid, sanitized_spec, error_message).
    """
    if not isinstance(raw, dict):
        return False, None, "Chart specification must be a JSON object"

    chart_type = raw.get("chart_type") or raw.get("type")
    if not chart_type or not isinstance(chart_type, str):
        return False, None, "Missing or invalid 'chart_type'"

    chart_type = chart_type.lower().strip()
    if chart_type not in VALID_CHART_TYPES:
        return False, None, f"Unsupported chart_type '{chart_type}'. Supported: {sorted(VALID_CHART_TYPES)}"

    title = str(raw.get("title") or "").strip()
    if not title:
        title = "Chart"

    subtitle = str(raw.get("subtitle") or "").strip()
    units = str(raw.get("units") or "").strip()
    legend = bool(raw.get("legend", True))
    tooltips = bool(raw.get("tooltips", True))
    percentage = bool(raw.get("percentage", False))

    sanitized: Dict[str, Any] = {
        "type": "chart",
        "chart_type": chart_type,
        "title": title,
        "subtitle": subtitle,
        "units": units,
        "legend": legend,
        "tooltips": tooltips,
        "percentage": percentage,
    }

    # Sources attribution
    sources = raw.get("sources")
    if isinstance(sources, list):
        sanitized["sources"] = sources
    else:
        sanitized["sources"] = []

    # 1. Pie & Donut Charts
    if chart_type in ("pie", "donut"):
        data = raw.get("data")
        # Alternative: allow series format with data items
        if not data and isinstance(raw.get("series"), list) and raw["series"]:
            first_series = raw["series"][0]
            if isinstance(first_series, dict) and "data" in first_series:
                data = first_series["data"]

        if not isinstance(data, list) or len(data) == 0:
            return False, None, f"{chart_type} chart requires a non-empty 'data' list of items"

        sanitized_data = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                return False, None, f"Item at index {i} in {chart_type} data must be an object"
            name = str(item.get("name") or item.get("label") or "").strip()
            if not name:
                return False, None, f"Item at index {i} is missing a valid 'name' or 'label'"

            val = item.get("value")
            if not _is_finite_number(val):
                return False, None, f"Item '{name}' has missing or non-numeric value: {val}"
            if val < 0:
                return False, None, f"Item '{name}' has negative value {val}; {chart_type} requires non-negative values"

            sanitized_data.append({"name": name, "value": float(val)})

        if sum(it["value"] for it in sanitized_data) <= 0:
            return False, None, f"{chart_type} chart must have total value greater than 0"

        sanitized["data"] = sanitized_data
        return True, sanitized, None

    # 2. Cartesian Charts: Bar, Line, Stacked-Bar
    categories = raw.get("categories")
    if not isinstance(categories, list) or len(categories) == 0:
        return False, None, f"{chart_type} chart requires a non-empty 'categories' list"

    sanitized_cats = [str(c).strip() for c in categories]
    if any(not c for c in sanitized_cats):
        return False, None, "Categories must not contain empty strings"

    num_cats = len(sanitized_cats)
    sanitized["categories"] = sanitized_cats

    series = raw.get("series")
    if not isinstance(series, list) or len(series) == 0:
        return False, None, f"{chart_type} chart requires a non-empty 'series' list"

    sanitized_series = []
    for s_idx, s in enumerate(series):
        if not isinstance(s, dict):
            return False, None, f"Series at index {s_idx} must be an object"
        s_name = str(s.get("name") or f"Series {s_idx + 1}").strip()
        s_data = s.get("data")
        if not isinstance(s_data, list):
            return False, None, f"Series '{s_name}' is missing 'data' list"

        if len(s_data) != num_cats:
            return False, None, (
                f"Series '{s_name}' data length ({len(s_data)}) does not match "
                f"categories length ({num_cats})"
            )

        sanitized_nums = []
        for val_idx, val in enumerate(s_data):
            if not _is_finite_number(val):
                return False, None, (
                    f"Series '{s_name}' contains non-numeric/missing value at position {val_idx}: {val}"
                )
            sanitized_nums.append(float(val))

        s_dict: Dict[str, Any] = {"name": s_name, "data": sanitized_nums}
        if chart_type == "stacked_bar":
            stack = s.get("stack") or "total"
            s_dict["stack"] = str(stack)

        sanitized_series.append(s_dict)

    sanitized["series"] = sanitized_series
    return True, sanitized, None


def validate_evidence_reference(raw: Any) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """
    Validate a PDF evidence reference dictionary.
    Returns (is_valid, sanitized_reference, error_message).
    """
    if not isinstance(raw, dict):
        return False, None, "Evidence reference must be a dictionary"

    filename = str(raw.get("filename") or raw.get("document") or raw.get("source") or "").strip()
    if not filename:
        return False, None, "Evidence reference requires a valid 'filename' or 'source'"

    page = raw.get("page")
    if page is not None:
        try:
            page = int(page)
            if page < 1:
                return False, None, "Page number must be a positive integer >= 1"
        except (ValueError, TypeError):
            return False, None, f"Invalid page number: {page}"

    bbox = raw.get("bounding_box") or raw.get("bbox")
    sanitized_bbox = None
    if bbox is not None:
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return False, None, "bounding_box must be a list of 4 numbers [x0, y0, x1, y1]"
        if not all(_is_finite_number(x) for x in bbox):
            return False, None, "bounding_box coordinates must be finite numbers"
        x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        if x0 > x1 or y0 > y1:
            return False, None, f"Invalid bounding_box coordinates ordering: [{x0}, {y0}, {x1}, {y1}]"
        sanitized_bbox = [x0, y0, x1, y1]

    snippet = str(raw.get("snippet") or raw.get("text_snippet") or "").strip()
    match_type = str(raw.get("match_type") or ("exact" if sanitized_bbox else "citation_only")).strip()

    sanitized = {
        "filename": filename,
        "page": page,
        "bounding_box": sanitized_bbox,
        "snippet": snippet,
        "match_type": match_type,
        "document_id": raw.get("document_id"),
    }
    return True, sanitized, None


def extract_chart_specs_from_text(text: str) -> List[Dict[str, Any]]:
    """
    Safely find, parse, and validate all chart JSON specifications embedded
    in model text. Non-matching or invalid chart JSON is strictly ignored.
    """
    if not text or not isinstance(text, str):
        return []

    charts = []
    for match in _CHART_BLOCK_RX.finditer(text):
        json_str = match.group(1).strip()
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict) and ("chart_type" in parsed or parsed.get("type") in VALID_CHART_TYPES):
                is_valid, spec, err = validate_chart_spec(parsed)
                if is_valid and spec:
                    charts.append(spec)
        except Exception:
            continue

    return charts
