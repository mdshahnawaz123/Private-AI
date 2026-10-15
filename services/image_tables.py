"""Ruled tables inside raster images (scanned pages, pasted screenshots).

A table pasted into a PDF as a picture (e.g. "Table 11" in the acoustic
report) was read by whole-image OCR into one flat stream of words, so values
lost their row/column and answers picked the wrong row. Like a careful human
reader, this first looks for the drawn table grid (horizontal + vertical rule
lines) with OpenCV, then OCRs each cell on its own and rebuilds the grid.
Images with no grid (photos, renders, charts) return None and are handled by
the existing OCR / vision path unchanged.
"""
import os


def _lines(mask, axis, min_len):
    import cv2
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1) if axis == 0 else (1, min_len))
    return cv2.dilate(cv2.erode(mask, kernel), kernel)


def _positions(profile, min_gap=4):
    out, run = [], None
    for i, v in enumerate(profile):
        if v and run is None:
            run = i
        elif not v and run is not None:
            out.append((run + i - 1) // 2)
            run = None
    if run is not None:
        out.append((run + len(profile) - 1) // 2)
    merged = []
    for p in out:
        if merged and p - merged[-1] < min_gap:
            merged[-1] = (merged[-1] + p) // 2
        else:
            merged.append(p)
    return merged


def detect_cells(image_path, min_rows=2, min_cols=2):
    """Return list of (row, col, x0, y0, x1, y1) cells, or None if no ruled grid."""
    import cv2
    import numpy as np
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    h, w = img.shape
    if h < 60 or w < 120:
        return None
    # Tables are printed on a light background; photos, renders and dark cover
    # graphics are not (a cover image produced 308 "cells" and a 4-minute OCR
    # timeout in testing). Skip anything that isn't mostly white.
    if (img > 235).mean() < 0.5:
        return None
    # Fixed darkness threshold, not adaptive: adaptive thresholding turns the
    # edge of a light cell SHADING into a fake rule line, which split shaded
    # columns in two and shifted every value one column right.
    mask = ((img < 150) * 255).astype(np.uint8)
    horiz = _lines(mask, 0, max(20, w // 30))
    vert = _lines(mask, 1, max(15, h // 30))
    grid = cv2.bitwise_or(horiz, vert)
    # Only accept a real table: enough long rules in both directions.
    rows_y = _positions((horiz.sum(axis=1) / 255) > w * 0.25)
    cols_x = _positions((vert.sum(axis=0) / 255) > h * 0.15)
    if len(rows_y) < min_rows + 1 or len(cols_x) < min_cols + 1:
        return None
    # Cells = connected regions of the grid's complement (handles merged cells).
    inv = 255 - grid
    inv[:rows_y[0], :] = 0
    inv[rows_y[-1]:, :] = 0
    inv[:, :cols_x[0]] = 0
    inv[:, cols_x[-1]:] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    cells = []
    for i in range(1, count):
        x, y, cw, ch, area = stats[i]
        if cw < 8 or ch < 8 or area < 0.5 * cw * ch:
            continue
        r = sum(1 for ry in rows_y if ry <= y + 1) - 1
        c = sum(1 for cx in cols_x if cx <= x + 1) - 1
        cells.append((r, c, x, y, x + cw, y + ch))
    if len({c[0] for c in cells}) < min_rows or len({c[1] for c in cells}) < min_cols:
        return None
    if len(cells) > 600:  # not a readable table; leave it to the image reader
        return None
    return sorted(cells, key=lambda c: (c[0], c[1], c[3], c[2]))


def crop_cells(image_path, cells, out_dir, scale=2.5):
    import cv2
    img = cv2.imread(image_path)
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for k, (r, c, x0, y0, x1, y1) in enumerate(cells):
        crop = img[y0 + 1:y1 - 1, x0 + 1:x1 - 1]
        if crop.size == 0:
            paths.append(None)
            continue
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        # Shaded cells (light blue/grey fill) defeat OCR; binarise to black on white.
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if (bw == 0).mean() > 0.5:
            bw = 255 - bw
        crop = cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR)
        crop = cv2.copyMakeBorder(crop, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        p = os.path.join(out_dir, f"k{k}_r{r}_c{c}.png")  # sub-cells share r/c
        cv2.imwrite(p, crop)
        paths.append(p)
    return paths


def grid_from_cells(cells, texts):
    """Rebuild rows x columns from cell boxes + texts.

    Columns come from the HEADER cells' horizontal spans (the most detailed
    header row first, then wider parent headers for columns it doesn't cover),
    and every body cell is placed under the header span its centre falls in.
    Using raw grid-line indices instead shifted values when the body had extra
    rule lines the header did not (shaded columns, sub-rows)."""
    rows = {}
    for (r, c, x0, y0, x1, y1), t in zip(cells, texts):
        rows.setdefault(r, []).append((x0, x1, (t or "").strip()))
    order = sorted(rows)
    if not order:
        return []
    import re
    def is_header(items):
        filled = [t for *_, t in items if t]
        return filled and not any(re.search(r"\d", t) and len(t) < 12 for t in filled)
    header_rows = []
    for r in order[:4]:
        if is_header(rows[r]):
            header_rows.append(r)
        else:
            break
    if not header_rows:
        header_rows = order[:1]
    spans = []
    for r in reversed(header_rows):  # most detailed (lowest) header row first
        for x0, x1, t in rows[r]:
            covered = sum(max(0, min(x1, b) - max(x0, a)) for a, b in spans)
            if t and covered <= 0.3 * (x1 - x0):
                spans.append((x0, x1))
    spans.sort()
    def col_of(x0, x1):
        cx = (x0 + x1) / 2
        for i, (a, b) in enumerate(spans):
            if a - 2 <= cx <= b + 2:
                return i
        return min(range(len(spans)), key=lambda i: abs((spans[i][0] + spans[i][1]) / 2 - cx))
    # One combined header row: every header cell (any level) that covers a
    # column contributes its text, top level first ("Noise Level ... - Aircraft
    # Takeoff Flyovers - Exceedance of Criteria").
    header = []
    for a, b in spans:
        parts = []
        for r in header_rows:
            for x0, x1, t in rows[r]:
                if t and min(x1, b) - max(x0, a) >= 0.5 * (b - a) and t not in parts:
                    parts.append(t)
        header.append(" - ".join(parts))
    out = [header]
    for r in order:
        if r in header_rows:
            continue
        row = [""] * len(spans)
        for x0, x1, t in rows[r]:
            if not t:
                continue
            i = col_of(x0, x1)
            row[i] = (row[i] + " " + t).strip()
        if any(row):
            out.append(row)
    return out


def table_from_image(image_path, timeout=240):
    """Grid rows for a ruled table image, cached beside the image as
    <image>.table.json ({"grid": [...]} or {"grid": null}). OCR runs in a child
    process (services.table_cells) like every other OCR call in the pipeline."""
    import json
    import subprocess
    import sys
    sidecar = image_path + ".table.json"
    if os.path.isfile(sidecar):
        with open(sidecar, encoding="utf-8") as handle:
            return json.load(handle).get("grid")
    grid = None
    cells = detect_cells(image_path)
    if cells:
        work = image_path + "_cells"
        paths = crop_cells(image_path, cells, work)
        jobs = [p for p in paths if p]
        manifest, output = os.path.join(work, "manifest.json"), os.path.join(work, "texts.json")
        with open(manifest, "w", encoding="utf-8") as handle:
            json.dump(jobs, handle)
        done = subprocess.run([sys.executable, "-m", "services.table_cells", manifest, output],
                              timeout=timeout, capture_output=True, text=True)
        if done.returncode:
            raise RuntimeError("Image table OCR failed: " + done.stderr[-400:])
        with open(output, encoding="utf-8") as handle:
            texts = json.load(handle)
        grid = grid_from_cells(cells, [texts.get(p, "") if p else "" for p in paths])
        # A real data table, not a boxed paragraph or a framed photo caption.
        if len(grid) < 3 or not any(any(ch.isdigit() for ch in c) for row in grid[1:] for c in row):
            grid = None
    with open(sidecar + ".tmp", "w", encoding="utf-8") as handle:
        json.dump({"grid": grid}, handle)
    os.replace(sidecar + ".tmp", sidecar)
    return grid
