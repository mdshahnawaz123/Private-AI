"""Design rules for Early Design (Phase 1).

One editable rule sheet drives every generator and check: cores, lifts, stairs,
travel distance, grid, parking, MEP rooms and unit sizes. Defaults are PLACEHOLDERS
in the spirit of the Dubai Building Code / UAE Fire Code; an admin must confirm them
against the authority rules for the project. Saved per installation in
data/early_design_rules.json (only changed values are stored).
"""
import json
import os
import threading

_LOCK = threading.Lock()

# key: (default, label, unit, group, note)
RULES = {
    # structure
    "grid_bay_m": (8.4, "Column grid bay", "m", "Structure", "Typical span; 8.1–8.4 m suits 3 parking bays between columns"),
    "column_size_m": (0.6, "Column size", "m", "Structure", ""),
    # vertical transport
    "units_per_lift": (70, "Residential units per passenger lift", "units", "Lifts", ""),
    "office_gfa_per_lift_m2": (4000, "Office GFA per passenger lift", "m²", "Lifts", ""),
    "single_lift_max_floors": (4, "Up to this many floors one lift is enough", "floors", "Lifts", ""),
    "service_lift_above_floors": (10, "Add a service lift above", "floors", "Lifts", ""),
    "fire_lift_above_height_m": (28.0, "Fire-fighting lift above building height", "m", "Lifts", "UAE Fire Code style threshold – confirm"),
    "lift_shaft_w_m": (2.6, "Lift shaft width", "m", "Lifts", ""),
    "lift_shaft_d_m": (2.7, "Lift shaft depth", "m", "Lifts", ""),
    "lift_lobby_d_m": (2.6, "Lift lobby depth", "m", "Lifts", ""),
    # stairs and egress
    "min_stairs": (2, "Minimum exit stairs per floor", "stairs", "Egress", ""),
    "single_stair_max_floors": (3, "Single stair allowed up to", "floors", "Egress", ""),
    "stair_w_m": (3.0, "Stair enclosure width", "m", "Egress", "Two flights of 1.2 m + well"),
    "stair_d_m": (6.4, "Stair enclosure depth", "m", "Egress", ""),
    "max_travel_m": (45.0, "Max travel distance to an exit stair (sprinklered)", "m", "Egress", "Confirm with UAE Fire Code for the occupancy"),
    "max_dead_end_m": (15.0, "Max dead-end corridor", "m", "Egress", ""),
    "corridor_w_m": (1.8, "Corridor width", "m", "Egress", ""),
    # shafts and MEP
    "riser_w_m": (1.6, "Services riser strip width (electrical, telecom, plumbing)", "m", "MEP", ""),
    "garbage_chute": (1, "Garbage chute room in residential cores (1 = yes)", "", "MEP", ""),
    "electrical_room_m2_per_1000_gfa": (2.0, "Floor electrical room per 1,000 m² floor", "m²", "MEP", ""),
    # parking (used in Phase 3)
    "bay_w_m": (2.5, "Parking bay width", "m", "Parking", ""),
    "bay_l_m": (5.5, "Parking bay length", "m", "Parking", ""),
    "aisle_two_way_m": (6.0, "Two-way aisle", "m", "Parking", ""),
    "ramp_slope_pct": (15.0, "Max ramp slope", "%", "Parking", ""),
    "park_studio": (1.0, "Bays per studio / 1-bed", "bays", "Parking", "Placeholder – confirm with DBC Ch. 4"),
    "park_2bed": (1.5, "Bays per 2-bed", "bays", "Parking", "Placeholder"),
    "park_3bed": (2.0, "Bays per 3-bed+", "bays", "Parking", "Placeholder"),
    "park_office_m2": (50.0, "Office: 1 bay per", "m² GFA", "Parking", "Placeholder"),
    "park_retail_m2": (40.0, "Retail: 1 bay per", "m² GFA", "Parking", "Placeholder"),
    # units
    "unit_studio_m2": (45.0, "Studio target size", "m²", "Units", ""),
    "unit_1bed_m2": (75.0, "1-bed target size", "m²", "Units", ""),
    "unit_2bed_m2": (110.0, "2-bed target size", "m²", "Units", ""),
    "unit_3bed_m2": (150.0, "3-bed target size", "m²", "Units", ""),
}


def _path():
    try:
        import db
        base = db.DATA_DIR
    except Exception:
        base = os.environ.get("EXPO_DATA_DIR") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    return os.path.join(base, "early_design_rules.json")


def _saved():
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def get():
    """Effective rules as {key: value}."""
    out = {k: v[0] for k, v in RULES.items()}
    for k, v in _saved().items():
        if k in RULES:
            out[k] = v
    return out


def sheet():
    """Rules with labels for the editor."""
    saved = _saved()
    eff = get()
    return [{"key": k, "value": eff[k], "default": d, "label": lab, "unit": u, "group": g, "note": n,
             "changed": k in saved} for k, (d, lab, u, g, n) in RULES.items()]


def save(changes, user=""):
    """Validate and store changed values (numbers only). Returns the effective rules."""
    clean = {}
    for k, v in (changes or {}).items():
        if k not in RULES:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{RULES[k][1]} must be a number")
        if fv < 0 or fv > 100000:
            raise ValueError(f"{RULES[k][1]} is out of range")
        clean[k] = int(fv) if isinstance(RULES[k][0], int) and fv.is_integer() else fv
    with _LOCK:
        cur = _saved()
        for k, v in clean.items():
            if v == RULES[k][0]:
                cur.pop(k, None)
            else:
                cur[k] = v
        cur["_updated_by"] = user
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=2)
        os.replace(tmp, _path())
    return get()
