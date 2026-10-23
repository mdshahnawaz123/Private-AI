"""Verified permanent purge of an already soft-deleted project's managed data.

No basename-prefix ownership guesses, no external backups/exports deletion,
and no success response when a known artifact or running worker remains.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil


class ProjectCleanupError(RuntimeError):
    status_code = 409


class ProjectCleanupIOError(ProjectCleanupError):
    status_code = 500


class ProjectCleanupNotFound(ProjectCleanupError):
    status_code = 404


def _receipt(data_dir, name):
    return Path(data_dir) / 'project_cleanup' / (hashlib.sha256(name.encode()).hexdigest() + '.json')


def project_is_retired(data_dir, name):
    return _receipt(data_dir, name).exists()


@contextmanager
def active_project_operation(data_dir, name):
    """Keep artifact creation mutually exclusive with permanent project cleanup."""
    import db
    validate_project_name(name)
    with _lock(_receipt(data_dir, name)):
        with db.SessionLocal() as session:
            project = session.query(db.Project).filter_by(name=name).first()
            if project is None or project.deleted_at is not None or project_is_retired(data_dir, name):
                raise ValueError('An active project is required; retired projects cannot create artifacts')
        yield


def allow_explicit_recreation(data_dir, name, remove=False):
    receipt = _receipt(data_dir, name)
    _validate(receipt, Path(data_dir).resolve())
    if receipt.exists():
        record = json.loads(receipt.read_text(encoding='utf-8'))
        if record.get('state') != 'COMPLETE':
            raise ValueError('Permanent project cleanup is incomplete; retry cleanup first')
        if remove:
            receipt.unlink()


def _write(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(record, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@contextmanager
def _lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if handle.tell() == 0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ProjectCleanupError('Another cleanup is already running') from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ProjectCleanupError('Another cleanup is already running') from exc
        yield


def _within(path, root):
    return path.resolve().is_relative_to(root.resolve()) and path.resolve() != root.resolve()


def _validate(path, root):
    if not _within(path, root):
        raise ProjectCleanupError('Cleanup target is outside application storage')
    # Reject junctions and symlinks at every parent, target and descendant.
    for part in (path, *path.parents):
        if part == root.parent:
            break
        if part.exists() or part.is_symlink():
            if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
                raise ProjectCleanupError('Linked cleanup paths require manual ownership review')
    if path.is_dir():
        for folder, dirs, files in os.walk(path, followlinks=False):
            for name in dirs + files:
                entry = Path(folder) / name
                if entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction()):
                    raise ProjectCleanupError('Linked artifact requires manual ownership review')


def _slug(name, kind):
    if kind == 'private':
        return re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('_') or 'project'
    value = re.sub(r'[^A-Za-z0-9 ._-]', '_', name)
    return (value.strip() or 'default') if kind == 'workspace' else value


def validate_project_name(name):
    if (not name or name in {'.', '..'} or any(c in name for c in '/\\:\x00')
            or name.endswith((' ', '.')) or PureWindowsPath(name).is_reserved()):
        raise ProjectCleanupError('Unsafe legacy project name requires manual migration')


def inventory(root, name, other_names, uploads):
    validate_project_name(name)
    for other in other_names:
        if other.rstrip(' .').casefold() == name.casefold() or any(
            _slug(other, kind).rstrip(' .').casefold() == _slug(name, kind).casefold()
            for kind in ('private', 'workspace', 'recycle')):
            raise ProjectCleanupError('Project storage names collide; refusing to delete shared paths')
        if (root/'docs'/other).resolve() == (root/'docs'/name).resolve():
            raise ProjectCleanupError('Project document directories resolve to shared storage')
    paths = {root/'docs'/name, root/'faiss_index'/name,
             root/'workspace'/_slug(name, 'workspace'), root/'projects'/name,
             root/'recycle_bin'/_slug(name, 'recycle'), root/'reports'/name}
    # Blender jobs have UUID directories; ownership comes from their manifest,
    # never from a filename prefix. Unknown manifests fail cleanup closed.
    blender = Path(os.getenv('EXPO_BLENDER_DATA', str(root/'blender_jobs'))).resolve()
    if blender.exists():
        for job in blender.iterdir():
            if not re.fullmatch(r'[0-9a-f]{32}', job.name):
                raise ProjectCleanupError('Unmapped Blender artifact requires ownership review')
            try:
                owner = json.loads((job/'job.json').read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise ProjectCleanupError('Unreadable Blender job ownership; cleanup not verified') from exc
            if owner.get('project') == name:
                if (job/'operation.lock').exists():
                    raise ProjectCleanupError('A Blender operation is active; retry cleanup after it finishes')
                _validate(job, root)
                paths.add(job)
    indexes = root/'faiss_index'
    if indexes.exists():
        for entry in indexes.iterdir():
            if entry.name.startswith((name+'.previous-', name+'.staging-')):
                if entry.name.casefold() in {n.casefold() for n in other_names}:
                    raise ProjectCleanupError('Index-generation path belongs to another project')
                paths.add(entry)
    recycled = root/'recycle_bin/_projects'
    pattern = re.compile(r'^\d{8}-\d{6}-' + re.escape(_slug(name, 'recycle')) + r'$')
    if recycled.exists():
        paths.update(entry for entry in recycled.iterdir() if pattern.fullmatch(entry.name))
    private = root/'private_uploads'
    if private.exists():
        for user in private.iterdir():
            if user.name.isdigit() and user.is_dir():
                paths.add(user/_slug(name, 'private'))
    for upload in uploads:
        expected = private/str(upload.user_id)/_slug(name, 'private')
        path = Path(upload.path)
        if not _within(path, expected):
            raise ProjectCleanupError('Private-upload path does not match the owning project')
        paths.add(expected)
    quarantine = root/'recovery/quarantine'
    if quarantine.exists():
        owners = list(quarantine.glob('*.owner.json'))
        mapped = set()
        source_roots = tuple(paths)
        for owner in owners:
            _validate(owner, root)
            record = json.loads(owner.read_text(encoding='utf-8'))
            artifact = Path(record['quarantined'])
            if artifact != Path(str(owner)[:-len('.owner.json')]):
                raise ProjectCleanupError('Invalid quarantine ownership record')
            _validate(artifact, root)
            original = Path(record['source']).resolve()
            if not _within(original, root):
                raise ProjectCleanupError('Unmapped quarantine ownership requires manual review')
            mapped.add(artifact)
            if any(original == p.resolve() or original.is_relative_to(p.resolve()) for p in source_roots):
                paths.update((artifact, owner))
        if any(p not in mapped and not p.name.endswith('.owner.json') for p in quarantine.iterdir()):
            raise ProjectCleanupError('Unmapped legacy quarantine files require ownership review before verified cleanup')
    for path in paths:
        _validate(path, root)
    # Only highest owning roots need removal; descendants are checked above.
    return sorted((p for p in paths if not any(p != q and p.is_relative_to(q) for q in paths)), key=str)


def assert_job_source_active(data_dir, source, payload):
    receipts = Path(data_dir)/'project_cleanup'
    if not receipts.exists():
        return
    path = Path(source).resolve()
    for receipt in receipts.glob('*.json'):
        record = json.loads(receipt.read_text(encoding='utf-8'))
        if payload.get('project') == record['project'] or any(
            path == Path(folder).resolve() or path.is_relative_to(Path(folder).resolve())
            for folder in record.get('paths', [])):
            raise ValueError('Project has been permanently retired; stale ingestion is blocked')


def purge_project(name, data_dir, queue, clear_caches=None):
    import db
    from sqlalchemy import text
    root = Path(data_dir).resolve()
    receipt = _receipt(root, name)
    _validate(receipt, root)
    with _lock(receipt), db.SessionLocal() as session:
        if session.bind.dialect.name == 'sqlite':
            session.execute(text('BEGIN IMMEDIATE'))
        project = session.query(db.Project).filter_by(name=name).with_for_update().first()
        previous = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else None
        if project is None and previous is None:
            raise ProjectCleanupNotFound('Project not found in the recycle bin')
        if project is not None and project.deleted_at is None:
            raise ProjectCleanupError('Delete the project into the recycle bin before permanent cleanup')
        project_id = project.id if project is not None else previous['project_id']
        others = [p.name for p in session.query(db.Project) if p.name != name]
        uploads = session.query(db.UserUpload).filter_by(project_id=project_id).all() if project is not None else []
        documents = session.query(db.Document).filter_by(project_id=project_id).all() if project is not None else []
        identities = {str(d.id) for d in session.query(db.Document)}
        identities.update(d.path for d in session.query(db.Document) if d.path)
        if any(a.document_id not in identities for a in session.query(db.Annotation)):
            raise ProjectCleanupError('Unmapped legacy annotations require ownership review before verified cleanup')
        for document in documents:
            if document.path and not _within(Path(document.path), root/'docs'/name):
                raise ProjectCleanupError('Document path is outside its owning project directory')
        paths = inventory(root, name, others, uploads)
        # Retain ownership roots across a crash even if their parent folders
        # have since disappeared. Do not trust a receipt to name arbitrary data.
        for old in (previous or {}).get('paths', []):
            candidate = Path(old)
            _validate(candidate, root)
            relative = candidate.relative_to(root).parts
            old_private = (len(relative) == 3 and relative[0] == 'private_uploads'
                           and relative[1].isdigit() and relative[2] == _slug(name, 'private'))
            old_generation = (len(relative) == 2 and relative[0] == 'faiss_index'
                              and relative[1].startswith((name+'.previous-', name+'.staging-'))
                              and relative[1].casefold() not in {n.casefold() for n in others})
            old_blender = (len(relative) == 2 and relative[0] == 'blender_jobs'
                           and re.fullmatch(r'[0-9a-f]{32}', relative[1]) is not None
                           and not candidate.exists())
            old_recycle = (len(relative) == 3 and relative[:2] == ('recycle_bin', '_projects')
                           and re.fullmatch(r'\d{8}-\d{6}-'+re.escape(_slug(name, 'recycle')), relative[2]))
            missing_quarantine = (len(relative) == 3 and relative[:2] == ('recovery', 'quarantine')
                                  and not candidate.exists())
            if candidate not in paths and not (old_private or old_generation or old_recycle or missing_quarantine or old_blender):
                raise ProjectCleanupError('Invalid ownership path in cleanup receipt')
            if candidate not in paths:
                paths.append(candidate)
        record = {'project': name, 'project_id': project_id, 'state': 'PENDING', 'paths': [str(p) for p in paths]}
        _write(receipt, record)
        try:
            with queue.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                owned = []
                for job in conn.execute('SELECT * FROM jobs'):
                    try:
                        payload = json.loads(job['payload'])
                    except (ValueError, TypeError):
                        payload = {}
                    source = Path(job['source']).resolve()
                    if payload.get('project') == name or payload.get('upload_id') in {u.id for u in uploads} or any(
                        source == p.resolve() or source.is_relative_to(p.resolve()) for p in paths):
                        if job['state'] == 'running':
                            raise ProjectCleanupError('A project job is running; wait for it to finish and retry')
                        owned.append(job['id'])
                for identity in owned:
                    conn.execute('DELETE FROM jobs WHERE id=?', (identity,))
                if clear_caches:
                    clear_caches(name, project_id)
                for path in paths:
                    _validate(path, root)
                    if path.is_dir():
                        shutil.rmtree(path)
                    elif path.exists():
                        path.unlink()
                # Repeat ownership discovery so a surviving/new artifact cannot
                # be hidden by a successful return based on the original list.
                remaining = [str(p) for p in set(paths + inventory(root, name, others, uploads)) if p.exists()]
                if remaining:
                    raise ProjectCleanupIOError('Project artifacts remain: ' + ', '.join(remaining))
                if project is not None:
                    db._purge_project_row(session, project)
                session.flush()
                for table in db.Base.metadata.tables.values():
                    if project is not None and 'project_id' in table.c:
                        if session.execute(table.select().where(table.c.project_id == record['project_id']).limit(1)).first():
                            raise ProjectCleanupIOError('Project rows remain in ' + table.name)

                # Purge Masterplan SQLite database records (D01)
                try:
                    from services.masterplan import db as mp_db
                    mp_ok = mp_db.delete_project_records(name)
                    if not mp_ok:
                        raise ProjectCleanupIOError(f"Masterplan DB purge failed for project '{name}'")
                    if record.get('project_id'):
                        mp_ok_pid = mp_db.delete_project_records(str(record['project_id']))
                        if not mp_ok_pid:
                            raise ProjectCleanupIOError(f"Masterplan DB purge failed for project id '{record['project_id']}'")
                except Exception as mp_err:
                    if isinstance(mp_err, ProjectCleanupError):
                        raise
                    raise ProjectCleanupIOError(f"Masterplan DB purge failed for '{name}': {mp_err}") from mp_err

                session.commit()
            record.update(state='COMPLETE', removed_jobs=len(owned))
            _write(receipt, record)
        except Exception as exc:
            session.rollback()
            record.update(state='FAILED', error=str(exc))
            _write(receipt, record)
            if isinstance(exc, ProjectCleanupError):
                raise
            raise ProjectCleanupIOError('Permanent cleanup incomplete; retry after resolving: ' + str(exc)) from exc
    db.audit('project.purge_now', project=name, detail={'cleanup_verified': True}, user=db.SYSTEM_USER)
    return {'status': 'purged', 'cleanup_verified': True, 'removed_jobs': len(owned)}
