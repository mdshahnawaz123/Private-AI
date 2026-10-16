"""Conservative hatch/label association using transformed block instances."""
import json
import re
from shapely.geometry import Polygon, Point


def linked_hatches(doc, source_name):
    labels, boundaries, leaders = [], [], []
    scales = {1:0.0254, 2:0.3048, 4:0.001, 5:0.01, 6:1.0}
    scale = scales.get(int(doc.header.get('$INSUNITS', 0)))

    def walk(entities, lineage=(), depth=0):
        if depth > 16:
            return
        for entity in entities:
            kind = entity.dxftype()
            original_entity = entity.source_of_copy or entity
            handle = original_entity.dxf.get('handle') or 'virtual'
            path = lineage + (str(handle),)
            if kind == 'INSERT':
                for attribute in entity.attribs:
                    labels.append((attribute.dxf.text, attribute.dxf.insert, path))
                try:
                    walk(entity.virtual_entities(), path + (entity.dxf.name,), depth+1)
                except Exception:
                    continue
            elif kind in ('TEXT','MTEXT'):
                text = entity.plain_text() if kind == 'MTEXT' else entity.dxf.text
                labels.append((text, entity.dxf.insert, path))
            elif kind == 'LEADER':
                annotation = doc.entitydb.get(entity.dxf.get('annotation_handle', ''))
                if annotation is not None and annotation.dxftype() in ('TEXT','MTEXT') and entity.vertices and entity.dxf.get('has_arrowhead', 1):
                    text = annotation.plain_text() if annotation.dxftype() == 'MTEXT' else annotation.dxf.text
                    leaders.append((text,entity.vertices[0],path[:-1] + ('leader_tip',str(handle))))
            elif kind == 'HATCH':
                # Holes, curved paths and non-horizontal planes need explicit support;
                # never measure their outer bounding box as a parcel.
                if len(entity.paths) != 1 or tuple(entity.dxf.extrusion) != (0.0,0.0,1.0):
                    continue
                boundary = entity.paths[0]
                vertices = getattr(boundary, 'vertices', None)
                if not vertices or not boundary.is_closed or any(abs(v[2]) > 1e-12 for v in vertices):
                    continue
                coords = [[float(v[0]),float(v[1])] for v in vertices]
                polygon = Polygon(coords)
                if polygon.is_valid and polygon.area > 0:
                    boundaries.append((polygon,coords,path,entity.dxf.layer))

    walk(doc.modelspace())
    for text,tip,path in leaders:
        # Explicit leader association overrides the label's insertion point.
        labels = [(t,pos,p) for t,pos,p in labels if not (t==text and p[:-1]==path[:-2])]
        labels.append((text,tip,path))
    associations = []
    for polygon,coords,path,layer in boundaries:
        inside = [(text,lineage) for text,pos,lineage in labels if polygon.covers(Point(pos.x,pos.y))]
        ids = set()
        for text,_ in inside:
            match = re.match(r'^\s*(?:P[- ]*)?(\d{5,8})(?=\s*(?:\||$))', text, re.I)
            if match: ids.add(match.group(1))
        if len(ids) != 1:
            continue
        pid = next(iter(ids))
        # Nested/overlapping hatches containing the same label are ambiguous.
        associations.append((pid,polygon,coords,path,layer,inside))
    counts = {pid:sum(item[0]==pid for item in associations) for pid,*_ in associations}
    result=[]
    for pid,polygon,coords,path,layer,inside in associations:
        if counts[pid] != 1:
            continue
        areas=[]
        for text,_ in inside:
            for line in text.splitlines():
                if 'gfa' in line.lower(): continue
                match=re.fullmatch(r'\s*([\d,]+(?:\.\d+)?)\s*(?:sqm|m²|m2)\s*',line,re.I)
                if match: areas.append(float(match.group(1).replace(',','')))
        annotation = areas[0] if len(set(areas))==1 else None
        measured = polygon.area*scale*scale if scale is not None else None
        evidence={'method':'hatch_label_containment','source':source_name,'entity_path':list(path),'layer':layer,
                  'drawing_units':int(doc.header.get('$INSUNITS',0)),'measured_area_sqm':measured,
                  'annotated_area_sqm':annotation,'labels':[t for t,_ in inside],
                  'label_paths':[list(p) for _,p in inside],'approval':'not_verified'}
        if measured is not None and annotation is not None:
            evidence['area_discrepancy_sqm']=annotation-measured
        points=[[x*scale,y*scale] for x,y in coords] if scale is not None else None
        anchors=[pos for text,pos,p in labels if 'leader_tip' in p and polygon.covers(Point(pos.x,pos.y))]
        anchor=[anchors[0].x*scale,anchors[0].y*scale] if scale is not None and len(anchors)==1 else None
        result.append({'plot_id':'P-'+pid,'area_sqm':measured if measured is not None else (annotation or 0),
                       'geometry':{'coordinates':points,'centroid':[polygon.centroid.x*scale,polygon.centroid.y*scale],'label_anchor':anchor} if points else None,
                       'land_use':'Unknown','status':'under_review','notes':json.dumps(evidence)})
    return result
