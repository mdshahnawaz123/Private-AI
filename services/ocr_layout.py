"""Rebuild OCR text in human reading order (2026-10-14 pipeline audit).

EasyOCR returns boxes roughly top-to-bottom across the WHOLE page width, so on
a two-column report page the two columns are interleaved line by line
("Mandatory Requirements / LEED (Assumed v4.1) / UAE Cabinet Decree ..."
mixed the left-column list with the right-column paragraph), and the model
then answered from that scrambled text. This detects a vertical gutter and
emits each column top-to-bottom, with full-width blocks (titles, banners,
tables spanning the page) kept in their vertical position.
"""


def _line_text(boxes):
    """Join boxes into lines (vertical overlap), left to right."""
    lines = []
    for b in sorted(boxes, key=lambda b: (b["y"], b["x"])):
        mid = b["y"] + b["h"] / 2
        for line in lines:
            if line["top"] - 2 <= mid <= line["bottom"] + 2:
                line["items"].append(b)
                line["top"] = min(line["top"], b["y"])
                line["bottom"] = max(line["bottom"], b["y"] + b["h"])
                break
        else:
            lines.append({"top": b["y"], "bottom": b["y"] + b["h"], "items": [b]})
    lines.sort(key=lambda l: l["top"])
    return [" ".join(i["text"] for i in sorted(l["items"], key=lambda i: i["x"])) for l in lines]


def _find_gutter(boxes, width):
    narrow = [b for b in boxes if b["w"] < 0.6 * width]
    if len(narrow) < 6:
        return None
    step = max(1.0, width / 400)
    bins = [0] * (int(width / step) + 2)
    for b in narrow:
        for i in range(int(b["x"] / step), int((b["x"] + b["w"]) / step) + 1):
            if i < len(bins):
                bins[i] += 1
    lo, hi = int(0.2 * width / step), int(0.8 * width / step)
    best, run_start, best_span = None, None, 0
    for i in range(lo, hi + 1):
        if bins[i] == 0:
            run_start = i if run_start is None else run_start
            if i - run_start + 1 > best_span:
                best_span, best = i - run_start + 1, (run_start + i) / 2 * step
        else:
            run_start = None
    if best is None or best_span * step < 0.02 * width:
        return None
    left = [b for b in narrow if b["x"] + b["w"] <= best]
    right = [b for b in narrow if b["x"] >= best]
    # Both columns must carry real text, otherwise it is just an indented page.
    if len(left) < 3 or len(right) < 3:
        return None
    return best


def reading_order_text(boxes):
    """boxes: [{'text', 'bounding_box': {'x','y','w','h'}}] -> text or None."""
    items = []
    for b in boxes or []:
        bb = b.get("bounding_box") or {}
        t = str(b.get("text") or "").strip()
        if t and all(k in bb for k in ("x", "y", "w", "h")):
            items.append({"text": t, "x": float(bb["x"]), "y": float(bb["y"]),
                          "w": float(bb["w"]), "h": float(bb["h"])})
    if not items:
        return None
    width = max(i["x"] + i["w"] for i in items) - min(i["x"] for i in items)
    x0 = min(i["x"] for i in items)
    for i in items:
        i["x"] -= x0
    gutter = _find_gutter(items, width)
    if gutter is None:
        return "\n".join(_line_text(items))
    out, band = [], {"L": [], "R": []}

    def flush():
        out.extend(_line_text(band["L"]))
        out.extend(_line_text(band["R"]))
        band["L"], band["R"] = [], []

    for b in sorted(items, key=lambda b: (b["y"], b["x"])):
        if b["x"] + b["w"] <= gutter:
            band["L"].append(b)
        elif b["x"] >= gutter:
            band["R"].append(b)
        else:  # spans the gutter: a heading/banner/table -- ends the column band
            flush()
            out.extend(_line_text([b]))
    flush()
    return "\n".join(out)
