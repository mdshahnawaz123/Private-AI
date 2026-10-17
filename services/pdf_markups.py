"""Native annotation round-tripping for PDFCraft, independent of browser overlays."""
import json
import math
import re
import html
import pymupdf as fitz

METADATA='expodesign-markups.json'
PREFIX='ExpoDesignMarkup:'
SUPPORTED={'cloud','callout','arrow','ellipse','text','bubble','count','symbol','pen','stamp','rect','highlight','note','distance','area'}

def read_markups(doc):
    if METADATA not in doc.embfile_names(): return []
    try:
        data=json.loads(doc.embfile_get(METADATA))
        if not isinstance(data,list) or len(data)>10000: return []
        return [m for m in data if isinstance(m,dict) and m.get('type') in SUPPORTED
                and isinstance(m.get('page'),int) and 1<=m['page']<=doc.page_count
                and re.fullmatch(r'[A-Za-z0-9_-]{1,120}',str(m.get('id','')))
                and re.fullmatch(r'#[0-9a-fA-F]{6}',str(m.get('color','')))]
    except (ValueError,TypeError): return []

def synchronize(doc,markups,author):
    if len(markups)>10000 or len(json.dumps(markups))>4_000_000: raise ValueError('Too many markups')
    for page in doc:
        for annot in list(page.annots()):
            if (annot.info.get('subject') or '').startswith(PREFIX): page.delete_annot(annot)
    saved=[]
    ids=set()
    for original in markups:
        m=dict(original);kind=m.get('type');identity=str(m.get('id',''))
        if kind not in SUPPORTED: raise ValueError('Unsupported markup type: '+str(kind))
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,120}',identity) or identity in ids: raise ValueError('Invalid/duplicate markup ID')
        ids.add(identity)
        number=int(m.get('page',0))
        if not 1<=number<=doc.page_count: raise ValueError('Markup page is out of range')
        page=doc[number-1];matrix=page.derotation_matrix
        def point(p):
            x,y=float(p['x']),float(p['y'])
            if not math.isfinite(x+y): raise ValueError('Invalid markup coordinates')
            return fitz.Point(x,y)*matrix
        def rectangle():
            values=m.get('rect') or [m.get('x',0),m.get('y',0),m.get('x',0)+m.get('w',120),m.get('y',0)+m.get('h',40)]
            if len(values)!=4 or not all(math.isfinite(float(v)) for v in values): raise ValueError('Invalid markup rectangle')
            r=fitz.Rect(values)*matrix
            if r.is_empty or r.is_infinite: raise ValueError('Empty markup rectangle')
            return r
        color=m.get('color','#ef4444')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',color): raise ValueError('Invalid markup color')
        rgb=tuple(int(color[i:i+2],16)/255 for i in (1,3,5))
        text=str(m.get('text',''))[:10000]
        if kind in ('rect','cloud','highlight'):
            r=rectangle()
            annot=page.add_highlight_annot(r) if kind=='highlight' else page.add_rect_annot(r)
            annot.set_colors(stroke=rgb)
            if kind=='cloud': annot.set_border(width=1.5,clouds=2)
        elif kind in ('arrow','distance'):
            pts=m.get('points') or [m.get('start'),m.get('end')]
            if len(pts)!=2 or not all(isinstance(p,dict) for p in pts): raise ValueError('Line markup requires two points')
            annot=page.add_line_annot(point(pts[0]),point(pts[1]));annot.set_colors(stroke=rgb)
            annot.set_line_ends(0,4)
            text=text or str(m.get('measurement',''))
        elif kind=='area':
            pts=m.get('points',[])
            if len(pts)<3: raise ValueError('Area markup requires polygon points')
            annot=page.add_polygon_annot([point(p) for p in pts]);annot.set_colors(stroke=rgb)
        elif kind=='ellipse':
            m.update(x=m['cx']-m['rx'],y=m['cy']-m['ry'],w=2*m['rx'],h=2*m['ry'])
            annot=page.add_circle_annot(rectangle());annot.set_colors(stroke=rgb)
        elif kind=='note':
            annot=page.add_text_annot(point(m),text)
        elif kind=='callout':
            box=m['box'];r=fitz.Rect(box['x'],box['y'],box['x']+box['w'],box['y']+box['h'])*matrix
            tip=point(m['arrow']);elbow=point(box)
            annot=page.add_freetext_annot(r,html.escape(text),fontsize=10,callout=[tip,elbow],border_color=rgb,text_color=rgb,richtext=True)
        else:
            # Native, editable labels for current point-based stamps/count/symbol tools.
            x,y=float(m.get('x',0)),float(m.get('y',0))
            r=fitz.Rect(x,y,x+180,y+45)*matrix
            label=str(m.get('stampType') or m.get('symbolLabel') or m.get('bubbleNum') or m.get('tallyNum') or text or kind)
            annot=page.add_freetext_annot(r,label,fontsize=11,text_color=rgb)
        annot.set_info(title=author,subject=PREFIX+identity,content=text)
        annot.update()
        m['author']=author;m['persisted']=True;saved.append(m)
    if METADATA in doc.embfile_names(): doc.embfile_del(METADATA)
    doc.embfile_add(METADATA,json.dumps(saved).encode(),filename=METADATA)
    return saved
