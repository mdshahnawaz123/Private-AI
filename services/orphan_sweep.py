"""Leftover-file sweeper (2026-10-15).

Removes storage that no longer belongs to any project, so deleting a project
or folder never leaves files behind:

  * data/docs/<name>, data/faiss_index/<name>(.previous-*/.staging-*),
    data/projects/<name>, data/workspace/<slug> whose project is gone from the
    database (soft-deleted projects are KEPT - they are still restorable);
  * data/cad_cache entries for DWG files that no longer exist in any project;
  * data/tmp files older than one hour.

Folders whose name starts with '_' (e.g. '__codes__' knowledge base) are never
touched. Every path is checked to be inside the data directory first.
"""
import os
import re
import shutil
import time
from pathlib import Path

from loguru import logger


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _remove(path, root, removed):
    if not _inside(path, root) or Path(path).resolve() == Path(root).resolve():
        return
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        removed.append(str(path))
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("orphan sweep: could not remove {}: {}", path, exc)


def sweep(data_dir=None, tmp_age_seconds=3600):
    import db
    from services.project_cleanup import _slug
    root = Path(data_dir or db.DATA_DIR).resolve()
    with db.SessionLocal() as s:
        names = [p.name for p in s.query(db.Project)]          # active AND soft-deleted
        docs = [d.path for d in s.query(db.Document) if d.path]
    keep = {n.casefold() for n in names}
    keep_ws = {_slug(n, 'workspace').casefold() for n in names}
    removed = []

    def _owned(entry, extra=()):
        n = entry.name
        if n.startswith('_') or n.startswith('.'):
            return True
        base = re.split(r'\.(?:previous|staging)-', n)[0]
        return n.casefold() in keep or base.casefold() in keep or n.casefold() in extra

    for sub, extra in (('docs', ()), ('faiss_index', ()), ('projects', ()), ('workspace', keep_ws)):
        folder = root / sub
        if folder.is_dir():
            for entry in folder.iterdir():
                if entry.is_dir() and not _owned(entry, extra):
                    _remove(entry, root, removed)

    # CAD conversion cache: keep only entries for DWGs that still exist.
    cache = root / 'cad_cache'
    if cache.is_dir():
        live = {re.sub(r'[^a-zA-Z0-9_\-\.]', '_', os.path.basename(p)) for p in docs
                if str(p).lower().endswith('.dwg') and os.path.exists(p)}
        for entry in cache.iterdir():
            m = re.match(r'^(.*\.dwg)_[0-9a-f]{12}_\d+\.(?:dxf|json)(?:\.tmp_\d+)?$', entry.name, re.I)
            if (m and m.group(1) not in live) or entry.name.find('.tmp_') > 0:
                _remove(entry, root, removed)

    tmp = root / 'tmp'
    if tmp.is_dir():
        cutoff = time.time() - tmp_age_seconds
        for entry in tmp.iterdir():
            try:
                if entry.stat().st_mtime < cutoff:
                    _remove(entry, root, removed)
            except FileNotFoundError:
                pass
    if removed:
        logger.info("Orphan sweep removed {} leftover item(s)", len(removed))
    return removed
