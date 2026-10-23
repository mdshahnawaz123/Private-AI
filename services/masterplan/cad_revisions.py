"""Source-preserving, allowlisted hatch edits saved as independent revisions."""
import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

COLORS={'yellow':0xffff00,'red':0xff0000,'green':0x00ff00,'blue':0x0080ff,'orange':0xffa500,'purple':0xa855f7,'cyan':0x00ffff,'pink':0xffc0cb,'teal':0x008080,'magenta':0xff00ff,'gold':0xffd700,'white':0xffffff}


def digest(path):
    with open(path,'rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def revision_folder(root,project,revision):
    if not re.fullmatch(r'[a-f0-9]{32}',revision):
        raise ValueError('Invalid revision ID')
    base=Path(root).resolve()/hashlib.sha256(project.encode()).hexdigest()
    folder=(base/revision).resolve()
    if not folder.is_relative_to(base.resolve()):
        raise ValueError('Invalid revision path')
    return folder


def read_revision(root,project,revision):
    folder=revision_folder(root,project,revision)
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if manifest['project']!=project:
        raise ValueError('Revision belongs to another project')
    for key in ('original','working'):
        path=folder/manifest[key]
        if path.parent.resolve()!=folder or not path.is_file():
            raise ValueError('Revision artifact missing')
        if digest(path)!=manifest[key+'_sha256']:
            raise ValueError('Revision artifact changed; withheld')
    return folder,manifest


def create_revision(root,project,source,plot_ids,color,actor,load_doc,save_doc,base_working=None,match_hatches=None):
    if match_hatches is None:
        from services.masterplan.parsers.hatch_link import linked_hatches
        match_hatches=linked_hatches
    if not isinstance(color,str) or color not in COLORS or not plot_ids:
        raise ValueError('Specify existing plot IDs and a supported color')
    source=Path(source).resolve()
    if source.suffix.lower() not in ('.dxf','.dwg') or not source.is_file():
        raise ValueError('Source drawing is unavailable')
    source_hash=digest(source)
    revision=uuid.uuid4().hex
    folder=revision_folder(root,project,revision)
    folder.mkdir(parents=True,exist_ok=False)
    original=folder/('original'+source.suffix.lower())
    shutil.copyfile(source,original)
    if digest(original)!=source_hash:
        raise ValueError('Source changed during snapshot')
    doc=load_doc(str(base_working or original))
    records={record['plot_id']:record for record in match_hatches(doc,source.name)}
    handles=[]
    from ezdxf.lldxf.tagwriter import TagCollector
    def fingerprint(entity):
        return [(tag.code,str(tag.value)) for tag in TagCollector.dxftags(entity)]
    before_entities={entity.dxf.handle:(entity.dxftype(),fingerprint(entity)) for block in doc.blocks for entity in block}
    for pid in plot_ids:
        if pid not in records:
            raise ValueError(f'{pid}: no unique supported source hatch; edit withheld')
        evidence=json.loads(records[pid]['notes'])
        handle=evidence['entity_path'][-1]
        entity=doc.entitydb.get(handle)
        if entity is None or entity.dxftype()!='HATCH':
            raise ValueError('Original hatch handle unavailable; edit withheld')
        # Editing a reused definition would change multiple instances.
        for block_name in evidence['entity_path'][1:-1:2]:
            count=sum(1 for block in doc.blocks for ins in block.query('INSERT') if ins.dxf.name==block_name)
            if count>1:
                raise ValueError('Shared block requires instance isolation before editing')
        entity.dxf.true_color=COLORS[color]
        handles.append(handle)
    working=folder/('working'+source.suffix.lower())
    save_doc(doc,str(working))
    checked=load_doc(str(working))
    for handle,(kind,attributes) in before_entities.items():
        entity=checked.entitydb.get(handle)
        actual=fingerprint(entity) if entity is not None else []
        if handle in handles:
            # ODA synchronizes the target hatch's ACI (62) with true color (420).
            # Both are intended color changes; all remaining tags must match.
            attributes=[tag for tag in attributes if tag[0] not in (62,420)]
            actual=[tag for tag in actual if tag[0] not in (62,420)]
        if entity is None or entity.dxftype()!=kind or actual!=attributes:
            raise ValueError('Non-target CAD entity changed during round-trip; revision withheld')
    for handle in handles:
        entity=checked.entitydb.get(handle)
        if entity is None or entity.dxf.get('true_color')!=COLORS[color]:
            raise ValueError('Saved hatch verification failed; edit withheld')
    if digest(source)!=source_hash or digest(original)!=source_hash:
        raise ValueError('Original changed; edit withheld')
    manifest={'revision':revision,'created_at':datetime.now(timezone.utc).isoformat(),'project':project,'source_name':source.name,'original':original.name,'working':working.name,
              'original_sha256':source_hash,'working_sha256':digest(working),'actor':actor,'plot_ids':plot_ids,
              'hatch_handles':handles,'color':color,'format':source.suffix.lower(),'validation':'target hatch color round-trip; full drawing fidelity requires review'}
    with (folder/'manifest.json').open('x',encoding='utf-8') as stream:
        json.dump(manifest,stream,indent=2)
    return manifest
