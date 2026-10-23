"""Early Design – Phase 2: structural grid and cores (stairs, lifts, lobby, risers).

Everything is sized from the design rules (services/design_rules.py) and from the
building (storeys, units, GFA, height), so cores grow or shrink with the design.
"""
import math

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union


def program(storeys, units_total, gfa_total, height_m, residential, rules, n_cores=1):
    """How many lifts / stairs the building needs, and how they split between cores."""
    if residential:
        need = math.ceil(units_total / max(1, rules["units_per_lift"]))
    else:
        need = math.ceil(gfa_total / max(1, rules["office_gfa_per_lift_m2"]))
    minimum = 1 if storeys <= rules["single_lift_max_floors"] else 2
    passenger = max(minimum, need)
    service = 1 if storeys > rules["service_lift_above_floors"] else 0
    fire = height_m > rules["fire_lift_above_height_m"]
    stairs_per_core = 1 if storeys <= rules["single_stair_max_floors"] else int(rules["min_stairs"])
    n_cores = max(1, n_cores)
    per = []
    for i in range(n_cores):
        p = passenger // n_cores + (1 if i < passenger % n_cores else 0)
        per.append({
            "passenger": max(1, p),
            "service": 1 if (service and i == 0) else 0,
            "fire": bool(fire),                      # one passenger lift per core doubles as fire lift
            "stairs": stairs_per_core if n_cores == 1 else max(1, stairs_per_core if i in (0, n_cores - 1) else 1),
        })
    if n_cores > 1 and sum(c["stairs"] for c in per) < rules["min_stairs"]:
        per[-1]["stairs"] = max(per[-1]["stairs"], 1)
    return {"passenger_required": passenger, "service_required": service, "fire_lift_required": fire,
            "stairs_per_floor": sum(c["stairs"] for c in per), "per_core": per,
            "basis": (f"{units_total} units / {rules['units_per_lift']} per lift" if residential
                      else f"{round(gfa_total):,} m² / {rules['office_gfa_per_lift_m2']:,} m² per lift")}


def core_size(pc, rules, residential):
    n_l = pc["passenger"] + pc["service"]
    W = pc["stairs"] * rules["stair_w_m"] + n_l * rules["lift_shaft_w_m"] + rules["riser_w_m"]
    D = max(rules["stair_d_m"], rules["lift_shaft_d_m"] + rules["lift_lobby_d_m"])
    return W, D


def layout(center, angle_deg, pc, rules, residential):
    """Core parts as [{type, label, poly}] plus the core outline, centred and rotated."""
    W, D = core_size(pc, rules, residential)
    x = -W / 2
    parts = []

    def add(t, label, x0, y0, x1, y1):
        parts.append({"type": t, "label": label, "poly": box(x0, y0, x1, y1)})

    sw, sd = rules["stair_w_m"], rules["stair_d_m"]
    lw, ld, lob = rules["lift_shaft_w_m"], rules["lift_shaft_d_m"], rules["lift_lobby_d_m"]
    if pc["stairs"] >= 1:
        add("stair", "STAIR", x, -D / 2, x + sw, -D / 2 + sd); x += sw
    lifts = []
    for i in range(pc["passenger"]):
        lifts.append(("lift_fire" if (pc["fire"] and i == 0) else "lift", "FIRE LIFT" if (pc["fire"] and i == 0) else "LIFT"))
    if pc["service"]:
        lifts.append(("lift_service", "SERVICE"))
    x_l0 = x
    for t, lab in lifts:
        add(t, lab, x, D / 2 - ld, x + lw, D / 2); x += lw
    if lifts:
        add("lobby", "LOBBY", x_l0, -D / 2, x, D / 2 - ld)
    rw = rules["riser_w_m"]
    if residential and rules.get("garbage_chute"):
        add("chute", "REFUSE", x, D / 2 - 1.8, x + rw, D / 2)
        add("riser", "RISERS", x, -D / 2, x + rw, D / 2 - 1.8)
    else:
        add("riser", "RISERS", x, -D / 2, x + rw, D / 2)
    x += rw
    if pc["stairs"] >= 2:
        add("stair", "STAIR", x, -D / 2, x + sw, -D / 2 + sd); x += sw
    outline = box(-W / 2, -D / 2, W / 2, D / 2)
    cx, cy = center
    tf = lambda g: affinity.translate(affinity.rotate(g, angle_deg, origin=(0, 0)), cx, cy)
    for p_ in parts:
        p_["poly"] = tf(p_["poly"])
    return tf(outline), parts


def frame_angle(poly):
    mrr = poly.minimum_rotated_rectangle
    c = list(mrr.exterior.coords)
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    e = e1 if math.hypot(*e1) >= math.hypot(*e2) else e2
    return math.degrees(math.atan2(e[1], e[0]))


def grid(fp, rules, avoid=None):
    """Column grid aligned with the footprint's main axis. Returns axes and columns."""
    bay = float(rules["grid_bay_m"])
    ang = frame_angle(fp)
    org = fp.centroid
    loc = affinity.rotate(fp, -ang, origin=org)
    minx, miny, maxx, maxy = loc.bounds
    def lines(lo, hi):
        n = max(1, int((hi - lo) // bay))
        off = ((hi - lo) - n * bay) / 2
        return [lo + off + k * bay for k in range(n + 1)]
    xs, ys = lines(minx, maxx), lines(miny, maxy)
    back = lambda g: affinity.rotate(g, ang, origin=org)
    axes = []
    for i, x in enumerate(xs):
        seg = back(LineString([(x, miny - 4), (x, maxy + 4)]))
        axes.append({"label": str(i + 1), "pts": [list(map(lambda v: round(v, 2), c)) for c in seg.coords]})
    for j, y in enumerate(ys):
        seg = back(LineString([(minx - 4, y), (maxx + 4, y)]))
        lab = chr(65 + j) if j < 26 else "A" + chr(65 + j - 26)
        axes.append({"label": lab, "pts": [list(map(lambda v: round(v, 2), c)) for c in seg.coords]})
    cs = float(rules["column_size_m"])
    inside = loc.buffer(-cs / 2)
    cols = []
    for x in xs:
        for y in ys:
            if inside.contains(Point(x, y)):
                c = back(box(x - cs / 2, y - cs / 2, x + cs / 2, y + cs / 2))
                if avoid is None or not avoid.intersects(c):
                    cols.append([[round(a, 2), round(b, 2)] for a, b in list(c.exterior.coords)[:-1]])
    return {"axes": axes, "columns": cols, "bay_m": bay, "angle_deg": round(ang, 2)}


def travel_check(units, stairs, rules):
    """Straight-line distance from each unit's entrance zone to the nearest stair (a
    simple early-design proxy; final routes are checked in detail design)."""
    if not stairs:
        return {"max_m": None, "ok": False, "limit_m": rules["max_travel_m"]}
    sp = [s.centroid for s in stairs]
    worst = 0.0
    for u in units:
        d = min(u.centroid.distance(p) for p in sp)
        worst = max(worst, d)
    return {"max_m": round(worst, 1), "ok": worst <= rules["max_travel_m"], "limit_m": rules["max_travel_m"]}
