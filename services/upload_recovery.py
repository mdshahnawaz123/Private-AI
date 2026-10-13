"""Exclusive leases distinguish active staging files from interrupted uploads."""
from contextlib import contextmanager
import os
import json
import hashlib
from pathlib import Path
import re
import uuid

@contextmanager
def staging_lease(staging_path):
    lock=Path(str(staging_path)+'.lock')
    handle=lock.open('a+b')
    try:
        if lock.stat().st_size==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:
        handle.close()

def quarantine_interrupted_uploads(roots,quarantine_dir,limit=128):
    """Preserve abandoned leased bytes; never touch active or legacy unleased files."""
    destination=Path(quarantine_dir).resolve();destination.mkdir(parents=True,exist_ok=True)
    results=[]
    for raw in roots:
        root=Path(raw).resolve()
        if not root.exists():continue
        for staging in root.rglob('*.upload-*'):
            if len(results)>=limit:return results
            if not re.search(r'\.upload-[a-f0-9]{32}$',staging.name):continue
            if not staging.is_file() or staging.is_symlink() or not staging.resolve().is_relative_to(root):continue
            lock=Path(str(staging)+'.lock')
            if not lock.is_file() or lock.is_symlink():continue
            try:
                with staging_lease(staging):
                    target=destination/(uuid.uuid4().hex+'-'+staging.name)
                    # Persist ownership before moving bytes; a crash must not
                    # leave anonymous project content in global quarantine.
                    owner=Path(str(target)+'.owner.json')
                    with staging.open('rb') as source:
                        digest=hashlib.file_digest(source,'sha256').hexdigest()
                    with owner.open('w',encoding='utf-8') as handle:
                        json.dump({'source':str(staging),'quarantined':str(target),'sha256':digest},handle)
                        handle.flush();os.fsync(handle.fileno())
                    os.replace(staging,target)
                    results.append({'source':str(staging),'quarantined':str(target),'status':'REUPLOAD_REQUIRED'})
            except OSError:
                continue  # Active uploads remain under their current owner's lease.
    return results
