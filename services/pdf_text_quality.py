"""Detect unusable decoded PDF text before sanitization destroys the evidence."""
import math
import unicodedata


def native_text_usable(text, min_chars=40):
    text = str(text or "")
    visible = [c for c in text if not c.isspace()]
    if len(visible) < min_chars:
        return False
    invalid = sum(unicodedata.category(c) in ("Cc", "Cs", "Co", "Cn") or c == "\ufffd" for c in visible)
    return invalid / len(visible) < 0.02


def page_text_rotation(page):
    """Orient raster OCR using dominant PDF text-line direction, without mutating PDF."""
    weights = {}
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            dx, dy = line.get("dir", (1, 0))
            angle = int(round(-math.degrees(math.atan2(dy, dx)) / 90)) * 90 % 360
            weight = sum(len(span.get("text", "")) for span in line.get("spans", []))
            weights[angle] = weights.get(angle, 0) + weight
    return max(weights, key=weights.get) if weights else 0
