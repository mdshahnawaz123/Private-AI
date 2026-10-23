"""Early Design feasibility engine (rule-based, no AI needed for the numbers).

Input : a plot boundary (metres), setbacks, planning limits, programme targets and
        parking rules.
Output: several massing options. Every number (GFA, FAR, coverage, floors, height,
        units, parking, basements) is CALCULATED here from the inputs, and each option
        carries a pass/fail list against the limits. Nothing is hard-coded per option.

Typologies
  podium_twin    podium + two towers on the long axis
  courtyard      perimeter block around a central courtyard
  slabs          parallel residential bars with a minimum spacing
  point_tower    one slender tower on a small podium + open plaza

The parking rates and limits are project inputs (defaults are placeholders): set
them to the authority / masterplan values for the plot.
"""
import io
import math

from shapely import affinity
from shapely.geometry import LineString, Polygon, MultiPolygon, box
from shapely.ops import unary_union

DEFAULTS = {
    "plot": [[0, 0], [125, 0], [125, 100], [0, 100]],
    "front_edge": 0,                 # index of the road-facing boundary edge
    "setback_front": 6.0, "setback_side": 4.5, "setback_rear": 6.0,
    "target_gfa": 35000.0,
    "max_far": 5.0, "max_coverage": 0.45, "max_height": 120.0, "max_floors": 40,
    "podium_floors": 3, "podium_ftf": 4.5, "typical_ftf": 3.3,
    "res_share": 0.80, "com_share": 0.15,          # rest = amenity
    "efficiency": 0.80, "avg_unit_nsa": 85.0,
    "tower_floorplate": 1100.0, "tower_spacing": 18.0,
    "courtyard_depth": 14.0, "slab_depth": 16.0, "slab_spacing": 20.0,
    "park_per_unit": 1.0, "park_visitor_pct": 0.10, "park_com_per_m2": 50.0,
    "bay_area": 30.0,                # m2 per bay incl. aisles/ramps
    "basement_efficiency": 0.85,
}

TYPES = [
    ("podium_twin", "Podium + twin towers"),
    ("courtyard", "Perimeter courtyard block"),
    ("slabs", "Parallel slab blocks"),
    ("point_tower", "Point tower + plaza"),
]


def _num(p, k):
    try:
        return float(p.get(k, DEFAULTS[k]))
    except (TypeError, ValueError):
        return float(DEFAULTS[k])


def params(raw):
    p = dict(DEFAULTS)
    for k, v in (raw or {}).items():
        if k in DEFAULTS and v is not None and v != "":
            p[k] = v
    for k in DEFAULTS:
        if k not in ("plot", "front_edge", "front_edges"):
            p[k] = _num(p, k)
    p["front_edge"] = int(p.get("front_edge") or 0)
    p["front_edges"] = [int(i) for i in ((raw or {}).get("front_edges") or []) if str(i).lstrip("-").isdigit()]
    p["podium_floors"] = int(round(p["podium_floors"]))
    p["max_floors"] = int(round(p["max_floors"]))
    for k in ("max_coverage", "res_share", "com_share", "efficiency", "park_visitor_pct", "basement_efficiency"):
        if p[k] > 1.0:
            p[k] = p[k] / 100.0
    return p


def plot_polygon(pts):
    if not pts or len(pts) < 3:
        raise ValueError("The plot needs at least 3 corner points.")
    poly = Polygon([(float(x), float(y)) for x, y in pts])
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area < 50:
        raise ValueError("The plot outline is not a valid closed shape.")
    if isinstance(poly, MultiPolygon):
        poly = max(poly.geoms, key=lambda g: g.area)
    return Polygon(poly.exterior.coords)


def buildable_area(plot, p):
    """Remove a strip of the right setback along every boundary edge.
    Front = the road-facing edge(s); rear = edges facing the opposite way; the rest are sides.
    Works for curved CAD outlines (many short segments) because roles come from edge direction."""
    coords = list(plot.exterior.coords)[:-1]
    n = len(coords)
    ccw = plot.exterior.is_ccw

    def normal(i):
        (x1, y1), (x2, y2) = coords[i], coords[(i + 1) % n]
        L = math.hypot(x2 - x1, y2 - y1) or 1
        dx, dy = (x2 - x1) / L, (y2 - y1) / L
        return (dy, -dx) if ccw else (-dy, dx)      # outward normal

    fronts = set(int(i) % n for i in (p.get("front_edges") or []) if str(i).lstrip("-").isdigit())
    if not fronts:
        fronts = {p["front_edge"] % n}
    fl = [i for i in fronts]
    wsum = [0.0, 0.0]
    for i in fl:
        L = math.dist(coords[i], coords[(i + 1) % n])
        nx, ny = normal(i)
        wsum[0] += nx * L; wsum[1] += ny * L
    nl = math.hypot(*wsum) or 1
    fn = (wsum[0] / nl, wsum[1] / nl)
    strips, roles = [], []
    for i in range(n):
        nx, ny = normal(i)
        dot = nx * fn[0] + ny * fn[1]
        role = "front" if i in fronts else "rear" if dot < -0.7 else "side"
        roles.append(role)
        s_ = {"front": p["setback_front"], "rear": p["setback_rear"], "side": p["setback_side"]}[role]
        if s_ > 0:
            strips.append(LineString([coords[i], coords[(i + 1) % n]]).buffer(s_, cap_style=2, join_style=2))
    b = plot.difference(unary_union(strips)) if strips else plot
    b = b.buffer(0)
    if isinstance(b, MultiPolygon) or b.geom_type == "GeometryCollection":
        polys = [g for g in getattr(b, "geoms", [b]) if g.geom_type == "Polygon"]
        b = max(polys, key=lambda g: g.area) if polys else Polygon()
    return b, roles


def _frame(poly):
    """Angle of the long axis, so options are laid out along the plot."""
    mrr = poly.minimum_rotated_rectangle
    c = list(mrr.exterior.coords)
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    e = e1 if math.hypot(*e1) >= math.hypot(*e2) else e2
    return math.degrees(math.atan2(e[1], e[0]))


def _fit_rect(local, area, aspect, anchor):
    """Largest rectangle up to `area` (w = aspect*d) that fits inside `local`,
    pushed towards anchor ('left'|'right'|'center'). Returns a polygon or None."""
    minx, miny, maxx, maxy = local.bounds
    a = area
    while a > 150:
        d = math.sqrt(a / aspect)
        w = aspect * d
        cy = (miny + maxy) / 2
        xs = []
        step = max(1.0, (maxx - minx) / 60)
        x = minx
        while x + w <= maxx + 1e-6:
            xs.append(x)
            x += step
        if anchor == "right":
            xs = xs[::-1]
        elif anchor == "center":
            mid = (minx + maxx - w) / 2
            xs.sort(key=lambda v: abs(v - mid))
        for x0 in xs:
            for dy in (0, -2, 2, -4, 4, -6, 6, -9, 9):
                r = box(x0, cy - d / 2 + dy, x0 + w, cy + d / 2 + dy)
                if local.buffer(0.01).contains(r):
                    return r
        a *= 0.92
    return None


def _floors_for(gfa_needed, plate):
    return max(1, math.ceil(gfa_needed / plate)) if plate > 1 else 0


def _option(kind, plot, build, p):
    """Return a list of masses: {poly, floors, ftf, base, use}."""
    ang = _frame(build)
    org = build.centroid
    local = affinity.rotate(build, -ang, origin=org)
    target = min(p["target_gfa"], p["max_far"] * plot.area * 0.998)
    pod_h = p["podium_floors"] * p["podium_ftf"]
    cap_cov = p["max_coverage"] * plot.area
    masses = []
    notes = []

    def back(g):
        return affinity.rotate(g, ang, origin=org)

    def tower_floor_limit(base_h):
        return max(1, min(p["max_floors"] - p["podium_floors"] if base_h else p["max_floors"],
                          int((p["max_height"] - base_h) // p["typical_ftf"])))

    if kind in ("podium_twin", "point_tower"):
        if kind == "podium_twin":
            podium = local
            if podium.area > cap_cov:
                podium = affinity.scale(local, *(2 * [math.sqrt(cap_cov / local.area)]), origin=local.centroid)
                podium = podium.intersection(local)
            ntow, plate, cap = 2, p["tower_floorplate"], 1800.0
        else:
            podium = affinity.scale(local, 0.45, 0.45, origin=local.centroid).intersection(local)
            ntow, plate, cap = 1, p["tower_floorplate"] * 0.85, 2200.0
        podium_gfa = podium.area * p["podium_floors"]
        rest = max(0.0, target - podium_gfa)
        # grow the floorplate (up to a slender-tower cap) when the height limit
        # would otherwise stop the towers reaching the target GFA
        avail = tower_floor_limit(pod_h)
        if rest > 0 and avail > 0:
            plate = min(max(plate, rest / (ntow * avail) * 1.02), max(plate, cap))
        towers = []
        if ntow == 2:
            minx, miny, maxx, maxy = podium.bounds
            gap = p["tower_spacing"]
            left = podium.intersection(box(minx, miny, (minx + maxx - gap) / 2, maxy))
            right = podium.intersection(box((minx + maxx + gap) / 2, miny, maxx, maxy))
            for half, anc in ((left, "left"), (right, "right")):
                if not half.is_empty:
                    r = _fit_rect(half, plate, 1.5, anc)
                    if r is not None:
                        towers.append(r)
        else:
            r = _fit_rect(podium, plate, 1.25, "center")
            if r is not None:
                towers.append(r)
        if not towers:
            notes.append("No tower floorplate fits on the podium; reduce the floorplate size or setbacks.")
        masses.append({"poly": back(podium), "floors": p["podium_floors"], "ftf": p["podium_ftf"], "base": 0.0,
                       "use": "podium"})
        if towers:
            per = rest / len(towers)
            limit = tower_floor_limit(pod_h)
            for t in towers:
                fl = min(limit, _floors_for(per, t.area)) if per > 0 else 0
                if per > 0 and _floors_for(per, t.area) > limit:
                    notes.append("Tower height limit reached: the target GFA cannot be fully met.")
                if fl:
                    masses.append({"poly": back(t), "floors": fl, "ftf": p["typical_ftf"], "base": pod_h,
                                   "use": "tower"})

    elif kind == "courtyard":
        d = p["courtyard_depth"]
        # straight-sided outline: curved CAD edges become clean wings with square corners
        tol = max(1.5, math.sqrt(local.area) * 0.025)
        outline = local.buffer(-tol, join_style=2).simplify(tol, preserve_topology=True)
        if outline.is_empty or outline.geom_type != "Polygon":
            outline = local

        def ring_for(inset):
            o = outline.buffer(-inset, join_style=2) if inset > 0 else outline
            if o.is_empty:
                return Polygon(), Polygon()
            if o.geom_type != "Polygon":
                o = max(_polys(o), key=lambda g: g.area)
            hole = o.buffer(-d, join_style=2)
            return (o.difference(hole) if not hole.is_empty else o), hole

        ring, hole = ring_for(0)
        lim = tower_floor_limit(0)
        need = _floors_for(target, min(ring.area, cap_cov))
        if need > lim:
            notes.append("Height limit reached: the target GFA cannot be fully met.")
        fl = max(1, min(lim, need))
        want = min(target / fl, cap_cov)
        if ring.area > want * 1.002:
            # pull the whole block in from the setback line (wing depth stays d)
            lo, hi = 0.0, math.sqrt(outline.area)
            for _ in range(40):
                mid = (lo + hi) / 2
                if ring_for(mid)[0].area > want:
                    lo = mid
                else:
                    hi = mid
            ring, hole = ring_for(hi)
        if hole.is_empty:
            notes.append("Plot too narrow for a courtyard; this option became a solid block.")
        if ring.area > cap_cov * 1.002:
            notes.append("Courtyard block exceeds the coverage limit.")
        masses.append({"poly": back(ring), "floors": fl, "ftf": p["typical_ftf"], "base": 0.0, "use": "block"})

    elif kind == "slabs":
        d, gap = p["slab_depth"], p["slab_spacing"]
        minx, miny, maxx, maxy = local.bounds
        bars = []
        y = miny
        while y + d <= maxy + 1e-6:
            bar = local.intersection(box(minx, y, maxx, y + d))
            if bar.area > 100:
                bars.append(bar)
            y += d + gap
        cov = sum(b.area for b in bars)
        while bars and cov > cap_cov:
            bars.pop()
            cov = sum(b.area for b in bars)
        if not bars:
            notes.append("No slab fits; reduce slab depth or spacing.")
        else:
            lim = tower_floor_limit(0)
            need = _floors_for(target, cov)
            if need > lim:
                notes.append("Height limit reached: the target GFA cannot be fully met.")
            fl = min(lim, need)
            for b in bars:
                masses.append({"poly": back(b), "floors": fl, "ftf": p["typical_ftf"], "base": 0.0, "use": "slab"})

    # Whole floors overshoot the target: shorten the bars / shrink the block so the
    # GFA lands on target instead of handing over 10% more area than asked for.
    if kind == "slabs" and masses:
        gfa = sum(m["poly"].area * m["floors"] for m in masses)
        if gfa > target * 1.001:
            f = (target * 0.998) / gfa
            for m in masses:
                g = m["poly"]
                if kind == "slabs":
                    lg = affinity.rotate(g, -ang, origin=org)
                    lg = affinity.scale(lg, f, 1.0, origin=lg.centroid)
                    g = affinity.rotate(lg, ang, origin=org)
                else:
                    g = affinity.scale(g, math.sqrt(f), math.sqrt(f), origin=g.centroid)
                m["poly"] = g.intersection(build)
    return masses, notes


def _polys(g):
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [g] if g.area > 0.01 else []
    out = []
    for x in getattr(g, "geoms", []):
        out.extend(_polys(x))
    return out


def _coords(g):
    out = []
    for q in _polys(g):
        out.append({"outer": [[round(x, 2), round(y, 2)] for x, y in list(q.exterior.coords)[:-1]],
                    "holes": [[[round(x, 2), round(y, 2)] for x, y in list(h.coords)[:-1]] for h in q.interiors]})
    return out


def _metrics(masses, plot, p):
    gfa = sum(m["poly"].area * m["floors"] for m in masses)
    footprint = unary_union([m["poly"] for m in masses]) if masses else Polygon()
    height = max((m["base"] + m["floors"] * m["ftf"] for m in masses), default=0.0)
    storeys = max((round(m["base"] / p["podium_ftf"]) if m["base"] else 0) + m["floors"] for m in masses) if masses else 0
    res, com = gfa * p["res_share"], gfa * p["com_share"]
    units = int(res * p["efficiency"] // p["avg_unit_nsa"])
    req = math.ceil(units * p["park_per_unit"] * (1 + p["park_visitor_pct"])
                    + (com / p["park_com_per_m2"] if p["park_com_per_m2"] > 0 else 0))
    per_level = int(plot.area * p["basement_efficiency"] // p["bay_area"])
    basements = math.ceil(req / per_level) if per_level else 0
    target = p["target_gfa"]
    m = {
        "gfa": round(gfa), "target_gfa": round(target), "gfa_pct_of_target": round(100 * gfa / target, 1) if target else None,
        "max_gfa_allowed": round(p["max_far"] * plot.area),
        "far": round(gfa / plot.area, 2), "coverage_pct": round(100 * footprint.area / plot.area, 1),
        "footprint_m2": round(footprint.area), "height_m": round(height, 1), "storeys": storeys,
        "residential_gfa": round(res), "commercial_gfa": round(com), "amenity_gfa": round(gfa - res - com),
        "units": units, "parking_required": req, "parking_per_basement": per_level, "basements_needed": basements,
        "parking_provided": basements * per_level, "open_space_pct": round(100 * (1 - footprint.area / plot.area), 1),
    }
    checks = [
        {"rule": "FAR", "limit": f"≤ {p['max_far']:g}", "value": m["far"], "ok": m["far"] <= p["max_far"] + 1e-6},
        {"rule": "Site coverage", "limit": f"≤ {100 * p['max_coverage']:g}%", "value": f"{m['coverage_pct']}%",
         "ok": m["coverage_pct"] <= 100 * p["max_coverage"] + 0.05},
        {"rule": "Height", "limit": f"≤ {p['max_height']:g} m", "value": f"{m['height_m']} m", "ok": m["height_m"] <= p["max_height"] + 1e-6},
        {"rule": "Floors", "limit": f"≤ {p['max_floors']}", "value": storeys, "ok": storeys <= p["max_floors"]},
        {"rule": "Target GFA", "limit": f"{round(target):,} m² (±3%)", "value": f"{m['gfa']:,} m²",
         "ok": abs(gfa - target) <= 0.03 * target},
    ]
    return m, checks


def _use_word(p):
    if p["res_share"] >= 0.6:
        return "residential"
    if p["res_share"] >= 0.3:
        return "mixed-use"
    return "office"


def _describe(kind, masses, m, p):
    use = _use_word(p)
    towers = [x for x in masses if x["use"] == "tower"]
    pod = next((x for x in masses if x["use"] == "podium"), None)
    pod_txt = f"{pod['floors']}-floor podium" if pod else "podium"
    if kind == "podium_twin":
        if not towers:
            return f"{pod_txt.capitalize()} only."
        t = " and ".join(f"{x['floors']}" for x in towers)
        return (f"{pod_txt.capitalize()} with two {use} towers of {t} floors above it "
                f"({m['storeys']} storeys in total, {m['height_m']} m).")
    if kind == "point_tower":
        if not towers:
            return f"{pod_txt.capitalize()} only."
        return (f"One slender {use} tower of {towers[0]['floors']} floors on a {pod_txt} "
                f"({m['storeys']} storeys in total), leaving {m['open_space_pct']}% of the plot open as plaza.")
    if kind == "courtyard":
        return f"Continuous {masses[0]['floors']}-storey {use} block around the plot edge with a central courtyard." if masses else ""
    if kind == "slabs":
        return f"{len(masses)} parallel {use} bars of {masses[0]['floors']} storeys, spaced for daylight." if masses else ""
    return ""


def render_prompt(kind, m, p=None, ctx=""):
    use = _use_word(p) if p else "residential"
    base_txt = {"residential": "residential", "mixed-use": "mixed-use residential and office", "office": "office"}[use]
    pod = "landscaped retail podium" if use != "office" else "glazed lobby podium"
    form = {
        "podium_twin": f"two {base_txt} towers of about {m['storeys']} storeys rising from a {pod}",
        "courtyard": f"a {m['storeys']}-storey perimeter {base_txt} block wrapping a green central courtyard",
        "slabs": f"a group of parallel {m['storeys']}-storey {base_txt} slab blocks with landscaped gardens between them",
        "point_tower": f"a single slender {m['storeys']}-storey {base_txt} tower on a {pod} beside a wide public plaza",
    }[kind]
    return (f"Eye-level architectural photograph of {form}, contemporary design, clean facade with vertical fins "
            f"and generous glazing, street trees and pedestrians in the foreground, soft daylight, realistic "
            f"materials, no text, no lettering, no signage{', ' + ctx if ctx else ''}.")


def generate(raw):
    p = params(raw)
    plot = plot_polygon(p["plot"])
    build, roles = buildable_area(plot, p)
    if build.is_empty or build.area < 100:
        raise ValueError("Nothing is left to build on after the setbacks.")
    wanted = raw.get("types") or [k for k, _ in TYPES]
    opts = []
    for kind, label in TYPES:
        if kind not in wanted:
            continue
        masses, notes = _option(kind, plot, build, p)
        met, checks = _metrics(masses, plot, p)
        opts.append({
            "kind": kind, "name": label, "summary": _describe(kind, masses, met, p),
            "metrics": met, "checks": checks, "passes": all(c["ok"] for c in checks), "notes": sorted(set(notes)),
            "masses": [{"use": x["use"], "floors": x["floors"], "base_m": round(x["base"], 2),
                        "top_m": round(x["base"] + x["floors"] * x["ftf"], 2), "area_m2": round(x["poly"].area),
                        "shapes": _coords(x["poly"])} for x in masses],
            "render_prompt": render_prompt(kind, met, p),
        })
    return {
        "plot": {"area_m2": round(plot.area), "shapes": _coords(plot),
                 "edges": [{"role": r} for r in roles], "front_edge": p["front_edge"] % len(roles),
                 "front_edges": [i for i, r in enumerate(roles) if r == "front"]},
        "buildable": {"area_m2": round(build.area), "shapes": _coords(build)},
        "context": raw.get("context") or [],
        "params": {k: v for k, v in p.items() if k != "plot"},
        "options": opts,
        "method": "Rule-based massing engine: geometry and every number are calculated from the inputs.",
    }


# ---------------------------------------------------------------- DXF in / out
_SITE_HINT = ("PLOT", "SITE", "BOUNDARY", "BOUND", "PARCEL", "AFFECTION")
_CTX_HINT = ("BLDG", "BUILDING", "CONTEXT", "SURROUND", "EXIST", "NEIGHB", "FOOTPRINT")


def read_site_dxf(data: bytes):
    """Find the plot outline (closed polyline, preferring a PLOT/SITE/BOUNDARY layer,
    otherwise the largest) and nearby existing buildings. Coordinates are shifted so
    the plot's lower-left corner is (0,0)."""
    import ezdxf
    from ezdxf import recover
    try:
        doc, _ = recover.read(io.BytesIO(data))
    except Exception:
        doc = ezdxf.read(io.StringIO(data.decode("utf-8", "ignore")))
    msp = doc.modelspace()
    scale = {4: 0.001, 5: 0.01, 6: 1.0}.get(doc.header.get("$INSUNITS", 6), 1.0)
    shapes = []
    for e in msp.query("LWPOLYLINE POLYLINE"):
        try:
            closed = e.closed if e.dxftype() == "LWPOLYLINE" else e.is_closed
            pts = [(v[0], v[1]) for v in (e.get_points("xy") if e.dxftype() == "LWPOLYLINE" else
                                          [(p.dxf.location.x, p.dxf.location.y) for p in e.vertices])]
        except Exception:
            continue
        if len(pts) >= 3 and (closed or math.dist(pts[0], pts[-1]) < 1e-6):
            poly = Polygon([(x * scale, y * scale) for x, y in pts]).buffer(0)
            if not poly.is_empty and poly.area > 1:
                if isinstance(poly, MultiPolygon):
                    poly = max(poly.geoms, key=lambda g: g.area)
                shapes.append((e.dxf.layer.upper(), poly))
    if not shapes:
        raise ValueError("No closed polyline found. Draw the plot as a closed polyline (layer PLOT or SITE).")
    site = [s for s in shapes if any(h in s[0] for h in _SITE_HINT)]
    layer, plot = max(site or shapes, key=lambda s: s[1].area)
    minx, miny = plot.bounds[0], plot.bounds[1]
    shift = lambda g: affinity.translate(g, -minx, -miny)
    plot = shift(plot)
    near = plot.buffer(max(60.0, math.sqrt(plot.area)))
    ctx = []
    for lay, g in shapes:
        g = shift(g)
        if g.equals(plot) or not near.intersects(g) or g.area > plot.area * 4:
            continue
        if any(h in lay for h in _CTX_HINT) or not site:
            if g.within(plot.buffer(0.5)):
                continue
            ctx.append([[round(x, 2), round(y, 2)] for x, y in list(g.exterior.coords)[:-1]])
    pts = [[round(x, 2), round(y, 2)] for x, y in list(plot.exterior.coords)[:-1]]
    return {"plot": pts, "context": ctx[:200], "layer": layer, "area_m2": round(plot.area)}


def option_dxf(result, index):
    """DXF (R2010) of one option: plot, setback line, context and 3D massing
    (each mass extruded with its real base level and height)."""
    import ezdxf
    opt = result["options"][index]
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 6
    for name, col in (("ED_PLOT", 1), ("ED_SETBACK", 2), ("ED_CONTEXT", 8), ("ED_PODIUM", 4), ("ED_TOWER", 5),
                      ("ED_BLOCK", 3), ("ED_TEXT", 7)):
        doc.layers.add(name, color=col)
    msp = doc.modelspace()
    for s in result["plot"]["shapes"]:
        msp.add_lwpolyline(s["outer"], close=True, dxfattribs={"layer": "ED_PLOT"})
    for s in result["buildable"]["shapes"]:
        msp.add_lwpolyline(s["outer"], close=True, dxfattribs={"layer": "ED_SETBACK", "linetype": "DASHED"})
    for c in result.get("context") or []:
        msp.add_lwpolyline(c, close=True, dxfattribs={"layer": "ED_CONTEXT"})
    for m in opt["masses"]:
        layer = {"podium": "ED_PODIUM", "tower": "ED_TOWER"}.get(m["use"], "ED_BLOCK")
        for s in m["shapes"]:
            for ring in [s["outer"]] + s["holes"]:
                msp.add_lwpolyline(ring, close=True, dxfattribs={
                    "layer": layer, "elevation": m["base_m"], "thickness": m["top_m"] - m["base_m"]})
            cx = sum(x for x, _ in s["outer"]) / len(s["outer"])
            cy = sum(y for _, y in s["outer"]) / len(s["outer"])
            msp.add_text(f"{m['use'].upper()} {m['floors']}F {m['area_m2']} m2",
                         dxfattribs={"layer": "ED_TEXT", "height": 1.5}).set_placement((cx, cy))
    mt = opt["metrics"]
    msp.add_mtext(
        f"{opt['name']}\\PGFA {mt['gfa']:,} m2  FAR {mt['far']}  Coverage {mt['coverage_pct']}%\\P"
        f"Height {mt['height_m']} m  Units {mt['units']}  Parking req. {mt['parking_required']}",
        dxfattribs={"layer": "ED_TEXT", "char_height": 2.0}).set_location((0, -8))
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------- masterplan plot
import re as _re


def parse_height(code):
    """'4B+G+18' -> (basements 4, floors above ground 19). 'G' -> (0, 1)."""
    s = str(code or "").upper().replace(" ", "")
    b = 0
    m = _re.search(r"(\d*)B(?![A-Z])", s)
    if m:
        b = int(m.group(1) or 1)
    fl = 0
    if "G" in s:
        fl = 1
        m = _re.search(r"G\+(\d+)", s)
        if m:
            fl += int(m.group(1))
        if _re.search(r"\+M\b|\+M\+", s):
            fl += 1
    return b, fl


MIX = {  # land use -> (residential share, commercial share)
    "residential": (0.90, 0.05), "mixed use": (0.75, 0.20), "commercial": (0.0, 0.90),
    "hospitality": (0.0, 0.90), "civic": (0.0, 0.85), "public facilities": (0.0, 0.85),
}


def plot_brief(plot, neighbours, schedule=None):
    """Turn an MPD plot record into Early Design inputs: outline shifted to a local
    origin, limits and targets from the plot schedule, road edge and surroundings.
    `schedule` = {plot_id: {...}} from the masterplan Excel: used to check that the CAD
    outline really belongs to this plot (land area must agree) and as the source of
    GFA / height."""
    g = (plot.get("geometry") or {}).get("coordinates") or []
    if len(g) < 3:
        raise ValueError(f"Plot {plot.get('plot_id')} has no CAD outline in the masterplan. "
                         "Import the masterplan DXF in MPD, or enter the plot size manually.")
    poly = plot_polygon(g)
    sched = (schedule or {}).get(str(plot.get("plot_id")).upper())
    if sched and sched.get("area_sqm"):
        sa = float(sched["area_sqm"])
        if abs(poly.area - sa) / sa > 0.01:
            owner = sorted((abs(float(v["area_sqm"]) - poly.area), pid) for pid, v in (schedule or {}).items()
                           if v.get("area_sqm") and abs(float(v["area_sqm"]) - poly.area) / poly.area < 0.001)
            owner = [pid for _, pid in owner[:2]]
            hint = f" It matches the land area of {', '.join(owner[:3])}." if owner else ""
            raise ValueError(
                f"The CAD outline linked to {plot.get('plot_id')} in the masterplan does not match the plot schedule: "
                f"outline {poly.area:,.0f} m² vs schedule land area {sa:,.0f} m².{hint} "
                "Please correct the CAD link in Masterplan (MPD) before designing this plot.")
        plot = dict(plot)
        for k in ("permitted_gfa", "max_height", "land_use", "sector"):
            if sched.get(k):
                plot[k] = sched[k]
        plot["area_sqm"] = sa
        if sched.get("permitted_gfa"):
            plot["max_far"] = round(float(sched["permitted_gfa"]) / sa, 3)
    sim = poly.simplify(0.3, preserve_topology=True)
    if sim.geom_type == "Polygon" and abs(sim.area - poly.area) / poly.area < 0.005:
        poly = sim
    ox, oy = poly.bounds[0], poly.bounds[1]
    loc = lambda pts: [[round(x - ox, 2), round(y - oy, 2)] for x, y in pts]
    pts = loc(list(poly.exterior.coords)[:-1])
    reach = poly.buffer(80)
    ctx, roads = [], []
    for n in neighbours:
        ng = (n.get("geometry") or {}).get("coordinates") or []
        if n.get("plot_id") == plot.get("plot_id") or len(ng) < 3:
            continue
        try:
            q = plot_polygon(ng)
        except ValueError:
            continue
        if not reach.intersects(q):
            continue
        use = str(n.get("land_use") or "").lower()
        if "road" in use or "row" in use or "sikka" in use or "parking" in use:
            roads.append(q)
        else:
            ctx.append(loc(list(q.exterior.coords)[:-1]))
    # front edge = the edge closest to a road plot (else the longest edge)
    cs = list(poly.exterior.coords)[:-1]
    edges = [LineString([cs[i], cs[(i + 1) % len(cs)]]) for i in range(len(cs))]
    fronts = []
    if roads:
        ru = unary_union(roads)
        dist = [ru.distance(e.interpolate(0.5, normalized=True)) for e in edges]
        fronts = [i for i, d in enumerate(dist) if d < 4.0]
        # keep the main frontage only: the side with the most road-facing length
        front = min(range(len(edges)), key=lambda i: (dist[i], -edges[i].length))
    else:
        front = max(range(len(edges)), key=lambda i: edges[i].length)
    if not fronts:
        fronts = [front]
    front = max(fronts, key=lambda i: edges[i].length)
    bas, floors = parse_height(plot.get("max_height"))
    use = str(plot.get("land_use") or "").lower()
    res, com = MIX.get(use, (0.8, 0.15))
    area = float(plot.get("area_sqm") or poly.area)
    gfa = float(plot.get("permitted_gfa") or 0) or float(plot.get("max_far") or 0) * area
    return {
        "plot": pts, "context": ctx[:150], "front_edge": front, "front_edges": fronts,
        "origin": [round(ox, 3), round(oy, 3)],
        "target_gfa": round(gfa), "max_far": float(plot.get("max_far") or 0) or round(gfa / area, 2),
        "max_coverage": float(plot.get("max_coverage_pct") or 50),
        "max_floors": floors or 40, "max_height": round((floors or 40) * 3.6 + 2, 1),
        "setback_front": float(plot.get("front_setback_m") or 0), "setback_side": float(plot.get("side_setback_m") or 0),
        "setback_rear": float(plot.get("rear_setback_m") or 0),
        "res_share": round(res * 100), "com_share": round(com * 100),
        "plot_info": {"plot_id": plot.get("plot_id"), "land_use": plot.get("land_use"), "sector": plot.get("sector"),
                      "area_sqm": round(area, 1), "outline_area_sqm": round(poly.area, 1),
                      "permitted_gfa": round(gfa), "max_height": plot.get("max_height"), "basements_allowed": bas,
                      "parking_required_schedule": plot.get("parking_required") or None,
                      "source": plot.get("notes") or "",
                      "checked_against_schedule": bool(sched)},
    }


# ---------------------------------------------------------------- typical floor plan
def _unit_type(a):
    return "Studio" if a < 50 else "1 Bed" if a < 85 else "2 Bed" if a < 125 else "3 Bed"


def floor_plan(result, option_index, p_raw=None, level="typical", rules=None):
    """Typical residential floor: units along the facade, corridor behind them,
    cores (lifts/stairs) on the corridor. Works on any footprint (tower, bar, ring)."""
    from shapely.ops import split
    p = params(p_raw or {})
    opt = result["options"][option_index]
    if level == "podium":
        cands = [m for m in opt["masses"] if m["use"] == "podium"]
        if not cands:
            raise ValueError("This option has no podium.")
    else:
        cands = [m for m in opt["masses"] if m["use"] != "podium"] or opt["masses"]
    if not cands:
        raise ValueError("This option has no building mass.")
    m = max(cands, key=lambda x: x["area_m2"])
    polys = [Polygon(s["outer"], s["holes"]) for s in m["shapes"]]
    fp = unary_union(polys)
    if isinstance(fp, MultiPolygon):
        fp = max(fp.geoms, key=lambda g: g.area)
    from services import design_rules as _dr
    from services import early_design_core as _core
    R = dict(_dr.get())
    R.update(rules or {})
    corr_w = float(R["corridor_w_m"])
    mrr = fp.minimum_rotated_rectangle
    import shapely
    r_in = shapely.maximum_inscribed_circle(fp, 0.25).length   # radius of the largest circle inside
    office = p["res_share"] < 0.3 or level == "podium"
    a = min(12.0 if office else 9.5, r_in - corr_w / 2 - 0.05)
    a = max(3.5, a)
    if list(fp.interiors):
        # rings (courtyards): wings are ~2·area/perimeter deep – keep a continuous corridor loop
        t_ring = 2 * fp.area / fp.length
        a = max(3.5, min(a, t_ring / 2 - corr_w / 2 - 0.1))
    # thin or curved footprints (rings, bent bars): make sure a corridor strip survives
    while a > 3.5 and fp.buffer(-a, join_style=2).area < 0.04 * fp.area:
        a -= 0.25
    inner = fp.buffer(-a, join_style=2)
    core_zone = inner.buffer(-corr_w, join_style=2)
    # deep plates: deepen the units rather than leave an oversized core (max ~12% of the floor)
    while (not list(fp.interiors)) and not core_zone.is_empty and core_zone.area > 0.12 * fp.area and a < 13.5:
        a += 0.5
        inner = fp.buffer(-a, join_style=2)
        core_zone = inner.buffer(-corr_w, join_style=2)
    band = fp.difference(inner)
    corridor = inner.difference(core_zone) if not core_zone.is_empty else inner
    # cut the facade band into units
    unit_w = max(6.0, (250.0 if office else p["avg_unit_nsa"]) / a)
    # cut lines square to each facade edge: at both ends of every straight edge
    # (gives clean corner units) and at even spacing along it
    cuts = []
    span = a + corr_w + 1
    rings = [fp.exterior] + list(fp.interiors)
    for ring in rings:
        cs = list(ring.coords)[:-1]
        for i in range(len(cs)):
            (x1, y1), (x2, y2) = cs[i], cs[(i + 1) % len(cs)]
            L = math.hypot(x2 - x1, y2 - y1)
            if L < 3.0:
                continue
            ux, uy = (x2 - x1) / L, (y2 - y1) / L
            nx, ny = -uy, ux
            n = max(1, round(L / unit_w))
            for k in range(n + 1):
                t = L * k / n
                px, py = x1 + ux * t, y1 + uy * t
                cuts.append(LineString([(px - nx * span, py - ny * span), (px + nx * span, py + ny * span)]))
    pieces = []
    cutter = unary_union(cuts) if cuts else None
    for part in _polys(band):
        if cutter is None:
            pieces.append(part)
            continue
        # carve with thin cut lines: robust where split() silently gives up
        pieces.extend(_polys(part.difference(cutter.buffer(0.03, cap_style=2))))
    # pieces still far larger than a unit (wide corners of irregular footprints):
    # cut them again into strips across their own long side
    target_u = unit_w * a
    big = [q for q in pieces if q.area > 2.5 * target_u]
    if big:
        pieces = [q for q in pieces if q.area <= 2.5 * target_u]
        for q in big:
            ang_q = _frame(q)
            lq = affinity.rotate(q, -ang_q, origin=q.centroid)
            minx, miny, maxx, maxy = lq.bounds
            k = max(2, round(q.area / target_u))
            stepx = (maxx - minx) / k
            for j in range(k):
                strip = box(minx + j * stepx, miny - 1, minx + (j + 1) * stepx, maxy + 1)
                pieces.extend(_polys(affinity.rotate(lq.intersection(strip), ang_q, origin=q.centroid)))
    # cores
    cores = []
    seeds = []          # (centre, angle) of each core
    compact = (not core_zone.is_empty and core_zone.geom_type == "Polygon" and not list(fp.interiors)
               and not list(core_zone.interiors))
    if compact and core_zone.area > 30:
        cores = _polys(core_zone)
        seeds = [((core_zone.centroid.x, core_zone.centroid.y), _core.frame_angle(fp))]
    else:
        # one spine per corridor piece: rings follow their loop, bars their long axis
        spines = []
        for g_ in (_polys(inner) if list(fp.interiors) else [fp]) or [mrr]:
            if list(g_.interiors):
                spines.append(g_.exterior)
            else:
                mr = g_.minimum_rotated_rectangle
                c_ = list(mr.exterior.coords)
                e1, e2 = (c_[0], c_[1]), (c_[1], c_[2])
                long_, short_ = (e1, e2) if math.dist(*e1) >= math.dist(*e2) else (e2, e1)
                mx, my = (short_[0][0] + short_[1][0]) / 2 - c_[1][0], (short_[0][1] + short_[1][1]) / 2 - c_[1][1]
                if long_ == e1:
                    sp_ = LineString([((c_[0][0] + c_[3][0]) / 2, (c_[0][1] + c_[3][1]) / 2), ((c_[1][0] + c_[2][0]) / 2, (c_[1][1] + c_[2][1]) / 2)])
                else:
                    sp_ = LineString([((c_[0][0] + c_[1][0]) / 2, (c_[0][1] + c_[1][1]) / 2), ((c_[2][0] + c_[3][0]) / 2, (c_[2][1] + c_[3][1]) / 2)])
                spines.append(sp_)
        for spine in spines:
            if spine.length < 8:
                continue
            # enough cores that no unit is further than the travel limit from a stair
            n = max(1, math.ceil(spine.length / 60), math.ceil(spine.length / (2 * float(R["max_travel_m"]) * 0.85)))
            for k in range(n):
                q = spine.interpolate((k + 0.5) / n, normalized=True)
                q2 = spine.interpolate(min(1.0, (k + 0.5) / n + 0.002), normalized=True)
                ang_s = math.degrees(math.atan2(q2.y - q.y, q2.x - q.x))
                cores.append(box(q.x - 4.5, q.y - 4.5, q.x + 4.5, q.y + 4.5).intersection(fp))
                seeds.append(((q.x, q.y), ang_s))
    core_u = unary_union(cores) if cores else Polygon()
    units, shafts = [], []
    small = []
    for u in pieces:
        u = u.difference(core_u)
        for g in _polys(u):
            (units if g.area >= 0.55 * (250.0 if office else p["avg_unit_nsa"]) else small).append(g)
    for g in sorted(small, key=lambda q: -q.area):
        best, bl = None, 0.0
        for k, u in enumerate(units):
            l = g.buffer(0.1).intersection(u).area
            if l > bl:
                best, bl = k, l
        if best is not None and units[best].area + g.area < 2.2 * (250.0 if office else p["avg_unit_nsa"]):
            units[best] = unary_union([units[best], g.buffer(0.06)]).buffer(-0.03)
        elif g.area >= 28:
            units.append(g)
        elif g.area > 1:
            shafts.append(g)
    units = [max(_polys(u), key=lambda q: q.area) for u in units if _polys(u)]
    core_parts, core_prog, checks, grid_out = [], None, [], None
    floors_m = m["floors"]
    if level != "podium" and seeds:
        met = opt["metrics"]
        residential = not office
        units_total = len(units) * floors_m
        core_prog = _core.program(met["storeys"], units_total, fp.area * floors_m, met["height_m"], residential, R, len(seeds))
        outlines = []
        notes_c = []
        for (cen_, ang_), pc in zip(seeds, core_prog["per_core"]):
            outline, parts = _core.layout(cen_, ang_, pc, R, residential)
            if not fp.buffer(0.05).contains(outline):
                notes_c.append("A core does not fit inside the floorplate; enlarge the floorplate or reduce lifts.")
            outlines.append(outline.intersection(fp))
            core_parts.extend(parts)
        designed = unary_union(outlines)
        if compact and not core_zone.is_empty:
            spare = core_zone.difference(designed)
            for g in _polys(spare):
                if g.area > 4:
                    core_parts.append({"type": "store", "label": "SERVICES", "poly": g})
            core_u = unary_union([designed, core_zone])
        else:
            core_u = designed
        keep_units = []
        for u in units:
            for g in _polys(u.difference(core_u)):
                (keep_units if g.area >= 28 else shafts).append(g)
        units = keep_units
        corridor = corridor.difference(core_u)
        stairs = [p_["poly"] for p_ in core_parts if p_["type"] == "stair"]
        tc = _core.travel_check(units, stairs, R)
        lifts_prov = sum(1 for p_ in core_parts if p_["type"] in ("lift", "lift_fire"))
        svc_prov = sum(1 for p_ in core_parts if p_["type"] == "lift_service")
        checks = [
            {"rule": "Passenger lifts", "limit": f"≥ {core_prog['passenger_required']} ({core_prog['basis']})", "value": lifts_prov,
             "ok": lifts_prov >= core_prog["passenger_required"]},
            {"rule": "Service lift", "limit": "required" if core_prog["service_required"] else "not required", "value": svc_prov,
             "ok": svc_prov >= core_prog["service_required"]},
            {"rule": "Fire-fighting lift", "limit": f"height > {R['fire_lift_above_height_m']} m" if core_prog["fire_lift_required"] else "not required",
             "value": "yes" if any(p_["type"] == "lift_fire" for p_ in core_parts) else "no",
             "ok": (not core_prog["fire_lift_required"]) or any(p_["type"] == "lift_fire" for p_ in core_parts)},
            {"rule": "Exit stairs per floor", "limit": f"≥ {int(R['min_stairs']) if met['storeys'] > R['single_stair_max_floors'] else 1}",
             "value": len(stairs), "ok": len(stairs) >= (int(R["min_stairs"]) if met["storeys"] > R["single_stair_max_floors"] else 1)},
            {"rule": "Travel distance to stair", "limit": f"≤ {tc['limit_m']} m", "value": f"{tc['max_m']} m", "ok": tc["ok"]},
        ]
        for n_ in notes_c[:1]:
            checks.append({"rule": "Core fits floorplate", "limit": "inside", "value": "no", "ok": False})
        grid_out = _core.grid(fp, R, avoid=core_u)
    units.sort(key=lambda g: (round(g.centroid.y, 0), g.centroid.x))
    U = []
    mix = {}
    for i, g in enumerate(units):
        t = "Tenancy" if office else _unit_type(g.area)
        mix[t] = mix.get(t, 0) + 1
        U.append({"id": f"{i + 1:02d}", "type": t, "area_m2": round(g.area, 1), "shapes": _coords(g)})
    gross = fp.area
    nsa = sum(g.area for g in units)
    floors = m["floors"]
    return {
        "core_label": "SERVICES / BOH" if level == "podium" else "CORE",
        "option": opt["name"], "mass": m["use"], "floors": floors, "level": level,
        "levels": (["typical", "podium"] if any(x["use"] == "podium" for x in opt["masses"]) else ["typical"]),
        "use": ("retail" if level == "podium" else "office") if office else "residential",
        "footprint": _coords(fp), "units": U,
        "corridor": _coords(corridor.difference(core_u)), "cores": [_coords(c)[0] for c in _polys(core_u) if c.area > 1],
        "core_parts": [{"type": p_["type"], "label": p_["label"], "shape": _coords(p_["poly"])[0]} for p_ in core_parts if _polys(p_["poly"])],
        "core_program": core_prog, "checks": checks, "grid": grid_out,
        "shafts": [s for g in shafts for s in _coords(g)],
        "summary": {"gross_m2": round(gross), "net_sellable_m2": round(nsa), "efficiency_pct": round(100 * nsa / gross, 1) if gross else 0,
                    "units_per_floor": len(U), "unit_mix": mix, "unit_depth_m": round(a, 1),
                    "corridor_width_m": corr_w, "cores": len([c for c in _polys(core_u) if c.area > 1]),
                    "units_in_this_mass": len(U) * floors},
    }
