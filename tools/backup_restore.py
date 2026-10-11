"""Offline backup/restore with source manifests. Stop the app before invoking.

Restores only into a new, empty destination; never overwrites a live data directory.
Use: python tools/backup_restore.py backup DATA_DIR BACKUP_DIR
     python tools/backup_restore.py restore BACKUP_DIR NEW_DATA_DIR
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from contextlib import contextmanager, closing


@contextmanager
def offline_lock(root):
    handle=open(Path(root)/'ingestion-runner.lock','a+b')
    if os.name=='nt':
        import msvcrt
        if handle.seek(0,2)==0:
            handle.write(b'0');handle.flush()
        handle.seek(0)
        try: msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            handle.close()
            raise RuntimeError('Stop the application before backup or restore')
    else:
        import fcntl
        try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise RuntimeError('Stop the application before backup or restore')
    try: yield
    finally: handle.close()


def digest(path):
    with open(path,'rb') as handle: return hashlib.file_digest(handle,'sha256').hexdigest()


def checked_destination(source,destination):
    source,destination=Path(source).resolve(),Path(destination).resolve()
    if not source.is_dir(): raise ValueError('Source directory does not exist')
    if destination==source or source in destination.parents or destination in source.parents:
        raise ValueError('Source and destination must be separate directories')
    if destination.exists() and any(destination.iterdir()): raise ValueError('Destination must be empty')
    destination.mkdir(parents=True,exist_ok=True)
    return source,destination


def backup(source,destination):
    source,destination=checked_destination(source,destination)
    files={}
    with offline_lock(source):
        for path in source.rglob('*'):
            if path.is_symlink(): raise ValueError('Symlinked data is not supported by offline backup')
            if not path.is_file() or path.name=='ingestion-runner.lock' or path.name.endswith(('-wal','-shm')): continue
            relative=path.relative_to(source)
            target=destination/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            if path.suffix in ('.db','.sqlite3'):
                with closing(sqlite3.connect(str(path))) as original,closing(sqlite3.connect(str(target))) as copy:
                    original.backup(copy)
                    if copy.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Database integrity check failed')
            else: shutil.copy2(path,target)
            files[relative.as_posix()]={'sha256':digest(target),'bytes':target.stat().st_size}
    (destination/'backup-manifest.json').write_text(json.dumps({'version':1,'source_root':str(source),'source_cwd':str(Path.cwd()),'files':files},indent=2),encoding='utf-8')
    return len(files)


def restore(source,destination):
    source,destination=checked_destination(source,destination)
    manifest=json.loads((source/'backup-manifest.json').read_text(encoding='utf-8'))
    validated=[]
    for relative,info in manifest['files'].items():
        path=(source/relative).resolve()
        target=(destination/relative).resolve()
        if source not in path.parents or destination not in target.parents or path.is_symlink():
            raise ValueError('Manifest path escapes the snapshot')
        if digest(path)!=info['sha256'] or path.stat().st_size!=info['bytes']:
            raise ValueError('Snapshot integrity mismatch: '+relative)
        validated.append((path,target))
    # Verify the complete manifest before writing any restored content.
    for path,target in validated:
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
    for path in destination.rglob('*'):
        if path.suffix in ('.db','.sqlite3'):
            with closing(sqlite3.connect(str(path))) as conn:
                if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Restored database integrity failure')
                # Relocate persisted filesystem references so the drill cannot
                # accidentally read the original application's document files.
                old_root=Path(manifest.get('source_root','')).resolve()
                old_cwd=Path(manifest.get('source_cwd','')).resolve()
                for table,column in [('documents','path'),('user_uploads','path'),('image_records','image_path'),('drawings','file_path'),('jobs','source')]:
                    columns={row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
                    if column not in columns: continue
                    for row_id,value in conn.execute(f'SELECT rowid,"{column}" FROM "{table}"'):
                        if not value:continue
                        original=Path(value)
                        original=(original if original.is_absolute() else old_cwd/original).resolve()
                        if old_root in original.parents:
                            relocated=str(destination/original.relative_to(old_root))
                            conn.execute(f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?',(relocated,row_id))
                if path.name=='ingestion-jobs.sqlite3':
                    for row_id,payload in conn.execute('SELECT rowid,payload FROM jobs'):
                        data=json.loads(payload)
                        value=data.get('save_path')
                        if value:
                            original=Path(value)
                            original=(original if original.is_absolute() else old_cwd/original).resolve()
                            if old_root in original.parents:
                                data['save_path']=str(destination/original.relative_to(old_root))
                                conn.execute('UPDATE jobs SET payload=? WHERE rowid=?',(json.dumps(data),row_id))
                conn.commit()
    return len(validated)


if __name__=='__main__':
    operation,source,destination=sys.argv[1:]
    if operation not in ('backup','restore'): raise ValueError('Use backup or restore')
    print(json.dumps({'operation':operation,'files':globals()[operation](source,destination)}))
