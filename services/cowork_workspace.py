"""Project-local Cowork files, folder tree management, and sandboxed Python execution."""
import os
import sys
import ast
import json
import tempfile
import subprocess
from pathlib import Path

READ_PAGE_CHARS = 12000
MAX_STDIO_CHARS = 16000

_SKIP_SUFFIXES = ('.extracted.txt', '.index.json', '.lock', '.tmp', '.pyc')
_SKIP_DIRS = {'.imports', '__pycache__', '.git', '.venv', 'node_modules'}
_MANIFEST_FILE = '.cowork_manifest.json'


def resolve_path(root, relative):
    root = Path(root).resolve()
    raw = str(relative or '.').replace('\\', '/').strip()
    if not raw:
        raw = '.'
    parts = [p for p in raw.split('/') if p not in ('', '.')]
    if raw.startswith('/') or any(':' in p or p == '..' for p in parts):
        raise ValueError('Use a relative path inside this project workspace')
    candidate = (root / '/'.join(parts)).resolve() if parts else root
    if candidate != root and root not in candidate.parents:
        raise ValueError('Path escapes the project workspace')
    return candidate


def _load_manifest(root_path: Path) -> set:
    mf = root_path / _MANIFEST_FILE
    if not mf.is_file():
        return set()
    try:
        data = json.loads(mf.read_text(encoding='utf-8'))
        return set(data.get('files', []))
    except Exception:
        return set()


def record_user_file(root, rel_path: str):
    """Record that a file was explicitly uploaded or generated in Cowork."""
    root_path = Path(root).resolve()
    clean = str(rel_path or '').replace('\\', '/').strip('/')
    if not clean:
        return
    files = _load_manifest(root_path)
    files.add(clean)
    mf = root_path / _MANIFEST_FILE
    try:
        mf.write_text(json.dumps({'files': sorted(files)}, indent=2), encoding='utf-8')
    except Exception:
        pass


def _extract_document_text(path_str: str) -> str:
    ext_txt = path_str + '.extracted.txt'
    if os.path.isfile(ext_txt):
        try:
            with open(ext_txt, 'r', encoding='utf-8', errors='ignore') as fh:
                cached = fh.read()
            if cached.strip():
                return cached
        except Exception:
            pass
    import extract
    lower = path_str.lower()
    if lower.endswith(('.xlsx', '.xlsm', '.xls')):
        res = extract.extract_excel(path_str)
        text = res[0] if isinstance(res, tuple) else str(res or '')
    elif lower.endswith('.pdf'):
        res = extract.extract_pdf(path_str, deep=False, smart=False)
        text = res[0] if isinstance(res, tuple) else str(res or '')
    elif lower.endswith('.docx'):
        res = extract.extract_docx(path_str)
        text = res[0] if isinstance(res, tuple) else str(res or '')
    else:
        text = ''
    if text:
        try:
            with open(ext_txt, 'w', encoding='utf-8', errors='ignore') as fh:
                fh.write(text)
        except Exception:
            pass
    return text or ''


def read_file_page(path, offset=0, limit=READ_PAGE_CHARS):
    """Offsets count decoded characters, not bytes; each response is bounded."""
    offset, limit = int(offset), int(limit)
    if offset < 0 or limit < 1:
        raise ValueError('offset must be nonnegative and limit must be positive')
    limit = min(limit, READ_PAGE_CHARS)
    before = os.stat(path)
    str_path = str(path)
    lower_path = str_path.lower()
    if lower_path.endswith(('.xlsx', '.xlsm', '.xls', '.pdf', '.docx')):
        text = _extract_document_text(str_path)
        content = text[offset:offset + limit]
        more = (offset + limit) < len(text)
        after = os.stat(path)
        return {
            'content': content,
            'offset': offset,
            'next_offset': offset + len(content),
            'total_chars': len(text),
            'eof': not more,
            'version': f'{after.st_mtime_ns}:{after.st_size}',
            'encoding': 'utf-8',
            'offset_unit': 'characters',
        }

    try:
        with open(path, 'r', encoding='utf-8-sig', errors='strict', newline='') as handle:
            remaining = offset
            while remaining:
                skipped = handle.read(min(remaining, 65536))
                if not skipped:
                    break
                remaining -= len(skipped)
            content = handle.read(limit)
            more = bool(handle.read(1))
    except UnicodeDecodeError:
        with open(path, 'r', encoding='utf-8', errors='replace', newline='') as handle:
            remaining = offset
            while remaining:
                skipped = handle.read(min(remaining, 65536))
                if not skipped:
                    break
                remaining -= len(skipped)
            content = handle.read(limit)
            more = bool(handle.read(1))

    if '\x00' in content:
        raise ValueError('Binary file: use run_python or document extraction rather than a text read')
    after = os.stat(path)
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise ValueError('File changed during reading; restart at offset 0')
    return {
        'content': content,
        'offset': offset,
        'next_offset': offset + len(content),
        'eof': not more,
        'version': f'{after.st_mtime_ns}:{after.st_size}',
        'encoding': 'utf-8-sig',
        'offset_unit': 'characters',
    }


def list_workspace_tree(root):
    """Return user-created folders and Cowork files/artifacts inside the workspace."""
    root_path = Path(root).resolve()
    manifest_files = _load_manifest(root_path)
    folders = []
    files = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = sorted([
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith('.')
        ])
        rel_dir = os.path.relpath(dirpath, root_path).replace('\\', '/')
        if rel_dir == '.':
            rel_dir = ''

        if rel_dir:
            try:
                st = os.stat(dirpath)
                mtime = int(st.st_mtime)
            except Exception:
                mtime = 0
            parent_dir = '/'.join(rel_dir.split('/')[:-1])
            folders.append({
                'path': rel_dir,
                'name': os.path.basename(dirpath),
                'parent': parent_dir,
                'mtime': mtime,
            })

        for fname in sorted(filenames):
            if fname.startswith('.') or fname.endswith(_SKIP_SUFFIXES):
                continue
            rel_file = f'{rel_dir}/{fname}' if rel_dir else fname
            # Only include root-level files if they were explicitly created/uploaded in Cowork
            # (prevents legacy auto-copied DOCS_DIR files from polluting the Cowork UI).
            if not rel_dir and rel_file not in manifest_files:
                continue
            full_path = os.path.join(dirpath, fname)
            try:
                st = os.stat(full_path)
            except Exception:
                continue
            ext = os.path.splitext(fname)[1].lower().lstrip('.')
            files.append({
                'path': rel_file,
                'name': fname,
                'folder': rel_dir,
                'ext': ext,
                'size': st.st_size,
                'mtime': int(st.st_mtime),
                'in_folder': bool(rel_dir),
            })

    # Count files per folder (including nested)
    for folder in folders:
        prefix = folder['path'] + '/'
        folder['file_count'] = sum(
            1 for f in files
            if f['folder'] == folder['path'] or f['folder'].startswith(prefix)
        )

    return {
        'root': str(root_path),
        'folders': folders,
        'files': files,
        'total_folders': len(folders),
        'total_files': len(files),
    }


def _snapshot_workspace(root_path: Path) -> dict:
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith('.')]
        for fname in filenames:
            if fname.startswith('.') or fname.endswith(_SKIP_SUFFIXES):
                continue
            fp = os.path.join(dirpath, fname)
            try:
                st = os.stat(fp)
                rel = os.path.relpath(fp, root_path).replace('\\', '/')
                snap[rel] = (st.st_mtime_ns, st.st_size)
            except Exception:
                pass
    return snap


BANNED_COWORK_MODULES = {
    "subprocess", "_winapi", "win32process", "win32api", "win32job", "ctypes", "socket",
    "http", "urllib", "requests", "httpx", "pty", "posix", "multiprocessing", "asyncio.subprocess"
}

PROHIBITED_INTROSPECTION = {
    "__mro__", "__bases__", "__subclasses__", "__globals__", "__code__", "__dict__", "__class__"
}


class _ASTConstantFolder(ast.NodeTransformer):
    """Statically fold string concatenations (e.g. 'File' + 'IO' -> 'FileIO') to prevent string splitting bypasses."""
    def visit_BinOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Add):
            if isinstance(node.left, ast.Constant) and isinstance(node.right, ast.Constant):
                if isinstance(node.left.value, str) and isinstance(node.right.value, str):
                    return ast.Constant(value=node.left.value + node.right.value)
        return node


def validate_cowork_ast(code: str):
    """Validate that script does not attempt prohibited system, process, introspection, or file-escape APIs."""
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise PermissionError(f"Invalid script syntax: {e}")

    # 1. Fold string concatenations so string-splitting evasion is resolved
    tree = _ASTConstantFolder().visit(tree)

    for node in ast.walk(tree):
        # 2. Direct imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split('.')[0].lower()
                if mod in BANNED_COWORK_MODULES:
                    raise PermissionError(f"Module '{alias.name}' is not permitted in the sandboxed workspace.")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mod = node.module.split('.')[0].lower()
                if mod in BANNED_COWORK_MODULES:
                    raise PermissionError(f"Module '{node.module}' is not permitted in the sandboxed workspace.")

        # 3. Dangerous identifier names
        elif isinstance(node, ast.Name):
            if node.id in ("__import__", "eval", "exec", "compile", "open_code"):
                raise PermissionError(f"Dynamic execution/import identifier '{node.id}' is not permitted.")

        # 4. Dangerous attribute accesses
        elif isinstance(node, ast.Attribute):
            attr = node.attr.lower()
            if attr in PROHIBITED_INTROSPECTION:
                raise PermissionError(f"Introspection attribute '{node.attr}' is prohibited in the sandboxed workspace.")
            if attr in ("__import__", "import_module"):
                raise PermissionError(f"Prohibited import attribute '{node.attr}' is not permitted.")
            if attr in ("system", "popen", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "fork", "execv", "execve"):
                raise PermissionError(f"Process execution attribute '{node.attr}' is not permitted.")
            if attr in ("fileio",):
                raise PermissionError(f"Direct raw FileIO attribute '{node.attr}' is not permitted.")

        # 5. Calls to getattr on system/builtin modules or with prohibited attributes
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "getattr":
                if len(node.args) >= 1:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Name) and first_arg.id.lower() in ("_io", "io", "builtins", "_builtins", "sys", "_sys", "os", "_os"):
                        raise PermissionError(f"Calling getattr on system module '{first_arg.id}' is prohibited in the sandboxed workspace.")
                if len(node.args) >= 2:
                    sec_arg = node.args[1]
                    if isinstance(sec_arg, ast.Constant) and isinstance(sec_arg.value, str):
                        val = sec_arg.value.strip().lower()
                        if val in PROHIBITED_INTROSPECTION or val in ("fileio", "__import__") or val in BANNED_COWORK_MODULES:
                            raise PermissionError(f"Dynamic access to prohibited attribute '{sec_arg.value}' via getattr is not permitted.")

        # 6. Dangerous string constants (arguments to dynamic imports, subscriptions, etc.)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value.strip().lower()
            if val in ("__import__", "fileio") or val in PROHIBITED_INTROSPECTION:
                raise PermissionError(f"Prohibited reference '{node.value}' is not permitted.")
            if val in BANNED_COWORK_MODULES or any(val == m or val.startswith(m + ".") for m in BANNED_COWORK_MODULES):
                raise PermissionError(f"Prohibited module reference '{node.value}' is not permitted.")
            if val in ("popen", "system", "spawnv"):
                raise PermissionError(f"Prohibited execution call '{node.value}' is not permitted.")

    return tree


def _create_sandboxed_job(max_processes: int = 1):
    """Creates a Windows Job Object that restricts active processes to 1 to block child processes."""
    if sys.platform != 'win32':
        return None
    try:
        import win32job
        job = win32job.CreateJobObject(None, '')
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        flags = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        info['BasicLimitInformation']['LimitFlags'] = flags
        info['BasicLimitInformation']['ActiveProcessLimit'] = max_processes
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        return job
    except Exception as e:
        raise PermissionError(f"Job Object sandbox initialization failed: {e}")


def check_os_isolation() -> tuple[bool, str]:
    """Only a reachable per-task engine counts; app containers and flags do not."""
    from services.container_sandbox import find_container_engine
    info = find_container_engine()
    return bool(info.get('daemon_running')), info.get('message', 'Isolated worker unavailable')


def run_workspace_python(root, code: str, cwd_rel: str = '.', timeout: int = 35) -> dict:
    """Run only in a disposable container; never fall back to host Python."""
    try:
        from services.container_sandbox import run_code_in_container
        result = run_code_in_container(code, root, cwd_rel=cwd_rel, timeout=timeout)
        for rel in result.get('changed_files', []):
            record_user_file(root, rel)
        return result
    except Exception as exc:
        return {'exit_code': 1, 'stdout': '', 'stderr': f'Isolated worker unavailable: {exc}',
                'changed_files': [], 'deleted_files': []}


def stage_text_write(root, relative, content):
    """Generated edits are artifacts in a new revision, never overwrites of input."""
    import hashlib
    import uuid
    root = Path(root).resolve()
    source = resolve_path(root, relative)
    if source == root:
        raise ValueError('Specify a file path')
    rel = source.relative_to(root)
    run_id = uuid.uuid4().hex
    folder = resolve_path(root, f'Cowork Runs/{run_id}')
    target = folder / 'working' / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    original_hash = None
    if source.is_file():
        import shutil
        original = folder / '.input' / rel
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, original)
        original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    target.write_text(content or '', encoding='utf-8')
    saved = target.relative_to(root).as_posix()
    result = {'status': 'staged', 'path': saved, 'changed_files': [saved],
              'original_path': rel.as_posix(), 'original_sha256': original_hash,
              'message': f'Saved a separate working copy at {saved}. Original unchanged.'}
    (folder / 'manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    record_user_file(root, saved)
    return result
