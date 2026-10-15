import hashlib
import json
import math
from pathlib import Path

import ezdxf
from shapely.geometry import Polygon, box


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def positive(value, label):
    if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{label}: explicit positive finite value required')
    return value


def extract(source, cfg):
    """Fail closed; never repair, snap, infer dimensions, or modify DXF."""
    doc = ezdxf.readfile(source)
    audit = doc.audit()
    if audit.errors or audit.fixes:
        raise ValueError('DXF audit reported errors/repairs; repair a copy in CAD and review it')
    scale = {1: .0254, 2: .3048, 4: .001, 5: .01, 6: 1}.get(doc.units)
    if scale is None:
        raise ValueError('Missing/unsupported INSUNITS; set verified units in CAD')
    height = positive(cfg.get('wall_height_m'), 'wall_height_m')
    slab = positive(cfg.get('slab_thickness_m'), 'slab_thickness_m')
    layers = cfg['layers']
    if set(layers) != {'wall', 'room', 'door', 'window'} or len(set(layers.values())) != 4:
        raise ValueError('Four distinct layer mappings required')
    reverse = {v: k for k, v in layers.items()}
    records, ignored = [], []
    for e in doc.modelspace():
        handle = e.dxf.handle
        kind = reverse.get(e.dxf.layer)
        if kind is None:
            if e.dxf.layer not in cfg.get('ignore_layers', []):
                raise ValueError(f'Unmapped layer {e.dxf.layer}, handle {handle}; map or explicitly ignore after review')
            ignored.append({'handle': handle, 'layer': e.dxf.layer, 'type': e.dxftype()})
            continue
        if e.dxftype() != 'LWPOLYLINE' or not e.closed or e.has_arc or e.has_width:
            raise ValueError(f'{handle}: requires closed zero-width straight LWPOLYLINE footprint')
        pts3 = list(e.vertices_in_wcs())
        if any(not all(math.isfinite(v) for v in p) or abs(p.z) > 1e-8 for p in pts3):
            raise ValueError(f'{handle}: only finite XY ground-plane footprints supported')
        pts = [(p.x * scale, p.y * scale) for p in pts3]
        poly = Polygon(pts)
        if not poly.is_valid or poly.area <= 1e-8 or len(pts) != 4 or not poly.equals(box(*poly.bounds)):
            raise ValueError(f'{handle}: MVP requires axis-aligned rectangular footprints; no approximation allowed')
        records.append({'id': handle, 'kind': kind, 'points': pts, 'bounds': list(poly.bounds), 'layer': e.dxf.layer})
    walls = [r for r in records if r['kind'] == 'wall']
    rooms = [r for r in records if r['kind'] == 'room']
    openings = [r for r in records if r['kind'] in ('door', 'window')]
    if not walls or not rooms:
        raise ValueError('At least one wall and room required')
    for i, a in enumerate(walls + rooms):
        for b in (walls + rooms)[i+1:]:
            if box(*a['bounds']).intersection(box(*b['bounds'])).area > 1e-8:
                raise ValueError(f'Overlapping footprints: {a["id"]}, {b["id"]}')
    metadata = cfg.get('openings', {})
    if set(metadata) != {o['id'] for o in openings}:
        raise ValueError('openings must contain exactly every door/window handle with verified sill_m and head_m')
    for o in openings:
        hosts = [w for w in walls if box(*w['bounds']).covers(box(*o['bounds']))]
        if len(hosts) != 1:
            raise ValueError(f'{o["id"]}: opening must be wholly inside exactly one wall footprint')
        w = hosts[0]
        axis = 0 if w['bounds'][2]-w['bounds'][0] >= w['bounds'][3]-w['bounds'][1] else 1
        cross = 1-axis
        if any(abs(o['bounds'][j]-w['bounds'][j]) > 1e-8 for j in (cross, cross+2)):
            raise ValueError(f'{o["id"]}: opening must span exact wall thickness')
        sill, head = metadata[o['id']]['sill_m'], metadata[o['id']]['head_m']
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (sill, head)) or not 0 <= sill < head <= height:
            raise ValueError(f'{o["id"]}: invalid opening vertical dimensions')
        if o['kind'] == 'door' and sill != 0:
            raise ValueError('Door sill must be zero in this MVP')
        o.update(host=w['id'], axis=axis, sill=sill, head=head)
    for i, a in enumerate(openings):
        for b in openings[i+1:]:
            if box(*a['bounds']).intersection(box(*b['bounds'])).area > 1e-8:
                raise ValueError('Overlapping openings')
    solids = []
    for w in walls:
        cuts = sorted([o for o in openings if o['host'] == w['id']], key=lambda o: o['bounds'][o['axis']])
        axis = cuts[0]['axis'] if cuts else 0
        cursor = w['bounds'][axis]
        def part(start, end, z0, z1):
            if end-start > 1e-8 and z1-z0 > 1e-8:
                bounds = w['bounds'].copy()
                bounds[axis], bounds[axis+2] = start, end
                solids.append({'source': w['id'], 'bounds': bounds, 'z0': z0, 'z1': z1})
        for o in cuts:
            lo, hi = o['bounds'][axis], o['bounds'][axis+2]
            part(cursor, lo, 0, height)
            part(lo, hi, 0, o['sill'])
            part(lo, hi, o['head'], height)
            cursor = hi
        part(cursor, w['bounds'][axis+2], 0, height)
    return {'schema': 1, 'source_sha256': hashlib.sha256(Path(source).read_bytes()).hexdigest(),
            'config_sha256': digest(cfg), 'units': 'metres', 'wall_height': height,
            'slab_thickness': slab, 'records': records, 'solids': solids, 'ignored': ignored}


CATALOG = {'sofa': [2.0, .85, .85], 'table': [1.1, .6, .45], 'chair': [.6, .6, .85]}


def validate_furniture(scene, items, clearance=.1):
    rooms = [box(*r['bounds']) for r in scene['records'] if r['kind'] == 'room']
    doors = [box(*r['bounds']).buffer(.9) for r in scene['records'] if r['kind'] == 'door']
    occupied = []
    for item in items:
        if set(item) != {'asset', 'x', 'y', 'rotation'} or item['asset'] not in CATALOG or item['rotation'] not in (0, 90, 180, 270):
            raise ValueError('Invalid furnishing catalog entry or rotation')
        if not all(isinstance(item[k], (int, float)) and math.isfinite(item[k]) for k in ('x', 'y')):
            raise ValueError('Furniture coordinates must be finite')
        w, d, _ = CATALOG[item['asset']]
        if item['rotation'] % 180:
            w, d = d, w
        x, y = item['x'], item['y']
        footprint = box(x-w/2, y-d/2, x+w/2, y+d/2)
        if not any(r.covers(footprint.buffer(clearance, join_style=2)) for r in rooms):
            raise ValueError('Furniture outside room or insufficient wall clearance')
        if any(footprint.intersects(p) for p in doors + occupied):
            raise ValueError('Furniture collision or door approach obstruction')
        occupied.append(footprint.buffer(clearance, join_style=2))
    return items
