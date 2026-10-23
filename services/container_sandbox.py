"""Disposable task containers with protected sources, bounded output and cleanup."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import threading
import time
import uuid

SANDBOX_IMAGE_NAME = "expodesignai-sandbox:latest"
FALLBACK_IMAGE_NAME = "python:3.12-slim"  # Compatibility only; never selected automatically.
MAX_OUTPUT = 65536
RUNS_FOLDER = "Cowork Runs"
KNOWN_ENGINE_PATHS = [
    r"C:\Program Files\Docker\Docker\resources\bin\docker.exe",
    r"C:\Program Files\RedHat\Podman\podman.exe",
]


def find_container_engine():
    cmd = shutil.which("docker") or shutil.which("podman")
    if not cmd:
        cmd = next((p for p in KNOWN_ENGINE_PATHS if os.path.isfile(p)), None)
    engine = "podman" if cmd and "podman" in Path(cmd).name.lower() else "docker"
    info = {"available": bool(cmd), "engine": engine if cmd else None,
            "path": cmd, "daemon_running": False}
    if not cmd:
        return {**info, "error_kind": "not_installed", "message": "Container engine not installed. Ask IT to provision Docker Desktop or Podman; typed application tools remain available."}
    try:
        proc = subprocess.run([cmd, "info", "--format", "{{.ServerVersion}}"],
                              capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            return {**info, "daemon_running": True, "version": proc.stdout.strip(),
                    "message": f"{engine} engine is ready."}
        detail = (proc.stderr or "").strip()[:600]
        denied = any(s in detail.lower() for s in ("permission denied", "access is denied", "access denied"))
        return {**info, "error_kind": "permission_denied" if denied else "unreachable",
                "message": ("Container API permission denied. Check this app account's engine access; this does not mean Docker is stopped. " if denied else "Container engine is unreachable. Check its service and connection settings. ") + detail}
    except subprocess.TimeoutExpired:
        return {**info, "error_kind": "timeout", "message": "Container readiness check timed out after 5 seconds."}
    except Exception as exc:
        return {**info, "error_kind": "probe_error", "message": f"Container readiness check failed: {exc}"}


def get_container_image(engine_path):
    proc = subprocess.run([engine_path, "image", "inspect", SANDBOX_IMAGE_NAME,
                           "--format", "{{.Id}}"], capture_output=True, text=True, timeout=5)
    if proc.returncode:
        raise RuntimeError("Approved Expo sandbox image is missing. Build it with tools/build_sandbox_image.bat; no image will be downloaded automatically.")
    value = proc.stdout.strip() if isinstance(proc.stdout, str) else ""
    return value or SANDBOX_IMAGE_NAME


def _digest(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_link(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _files(root):
    result = {}
    for parent, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = Path(parent) / name
            if _is_link(path):
                raise ValueError("Linked task artifacts are not accepted")
        for name in names:
            path = Path(parent) / name
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("Only regular task files are accepted")
            result[path.relative_to(root).as_posix()] = _digest(path)
    return result


def _stage(root, inputs, working):
    for parent, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in (RUNS_FOLDER, '__pycache__', 'node_modules')]
        for name in dirs + names:
            if _is_link(Path(parent) / name):
                raise ValueError("Workspace contains a link/reparse point; stage ordinary files first")
        rel = Path(parent).relative_to(root)
        (inputs / rel).mkdir(parents=True, exist_ok=True)
        (working / rel).mkdir(parents=True, exist_ok=True)
        (working / rel).chmod(0o777)
        for name in names:
            if name.startswith('.'):
                continue
            source = Path(parent) / name
            if not source.is_file():
                raise ValueError("Unsupported workspace entry")
            shutil.copy2(source, inputs / rel / name)
            shutil.copy2(source, working / rel / name)
            (working / rel / name).chmod(0o666)
    return _files(inputs)


def _remove_container(engine, name):
    done = subprocess.run([engine, "rm", "--force", name], capture_output=True, text=True, timeout=12)
    if done.returncode and "no such container" not in (done.stderr or "").lower():
        raise RuntimeError(f"Could not confirm removal of {name}: " + (done.stderr or "")[:300])


def _execute(command, engine, name, timeout):
    """Drain bounded logs and always destroy this task's named container."""
    proc = None
    chunks = {"stdout": [], "stderr": []}
    excessive = threading.Event()
    readers = []
    reason = ""
    exit_code = 1
    def read(pipe, key):
        count = 0
        try:
            while True:
                value = pipe.read(4096)
                if not value:
                    break
                room = max(0, MAX_OUTPUT - count)
                if room:
                    chunks[key].append(value[:room])
                count += len(value)
                if count > MAX_OUTPUT:
                    excessive.set()
        finally:
            pipe.close()
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for key in chunks:
            thread = threading.Thread(target=read, args=(getattr(proc, key), key), daemon=True)
            thread.start()
            readers.append(thread)
        deadline = time.monotonic() + timeout
        while proc.poll() is None:
            if excessive.is_set():
                reason = "Task stopped: output exceeded the 64 KB limit."
                exit_code = 125
                break
            if time.monotonic() >= deadline:
                reason = f"Task timed out after {timeout} seconds and was stopped."
                exit_code = 124
                break
            time.sleep(.05)
        else:
            exit_code = proc.returncode
    finally:
        try:
            _remove_container(engine, name)
        finally:
            if proc is not None:
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=5)
            for thread in readers:
                thread.join(timeout=3)
    stdout = b"".join(chunks['stdout']).decode('utf-8', errors='replace')
    stderr = b"".join(chunks['stderr']).decode('utf-8', errors='replace')
    if excessive.is_set() and exit_code == 0:
        exit_code, reason = 125, "Task output exceeded the 64 KB limit."
    return exit_code, stdout, (stderr + "\n" + reason).strip()


def run_code_in_container(code, workspace_root, cwd_rel='.', timeout=45, snapshot_func=None):
    result = {"exit_code": 1, "stdout": "", "stderr": "", "changed_files": [],
              "deleted_files": [], "staged_only": True}
    try:
        info = find_container_engine()
        if not info.get('daemon_running'):
            result['stderr'] = info['message']
            return result
        engine = info['path']
        image = get_container_image(engine)
        root = Path(workspace_root).resolve(strict=True)
        cwd = (root / (cwd_rel or '.')).resolve()
        relative_cwd = cwd.relative_to(root)  # Validate before any directory creation.
        if not root.is_dir():
            raise ValueError('Workspace directory required')
        run_id = uuid.uuid4().hex
        folder = root / RUNS_FOLDER / run_id
        if (root / RUNS_FOLDER).exists() and _is_link(root / RUNS_FOLDER):
            raise ValueError('Task history cannot be a link')
        inputs, working, runner = folder / '.input', folder / 'working', folder / '.runner'
        inputs.mkdir(parents=True)
        working.mkdir()
        runner.mkdir()
        before = _stage(root, inputs, working)
        (working / relative_cwd).mkdir(parents=True, exist_ok=True)
        (working / relative_cwd).chmod(0o777)
        script = runner / 'task.py'
        script.write_text(code or '', encoding='utf-8')
        script.chmod(0o444)
        name = 'expo-task-' + run_id
        result['run_id'] = run_id
        command = [engine, 'run', '--name', name, '--rm', '--pull=never',
                   '--network', 'none', '--memory', '1024m', '--memory-swap', '1024m',
                   '--cpus', '1.5', '--pids-limit', '64', '--user', '1000:1000',
                   '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--read-only',
                   '--tmpfs', '/tmp:rw,noexec,nosuid,size=128m,mode=1777',
                   '--mount', f'type=bind,source={inputs.as_posix()},target=/input,readonly',
                   '--mount', f'type=bind,source={working.as_posix()},target=/workspace',
                   '--mount', f'type=bind,source={runner.as_posix()},target=/runner,readonly',
                   '-w', '/workspace' + ('/' + relative_cwd.as_posix() if relative_cwd.parts else ''),
                   '-e', 'PYTHONIOENCODING=utf-8', '-e', 'PYTHONDONTWRITEBYTECODE=1',
                   '-e', 'MPLCONFIGDIR=/tmp/matplotlib', '-e', 'MPLBACKEND=Agg',
                   image, 'python', '-u', '/runner/task.py']
        exit_code, stdout, stderr = _execute(command, engine, name, max(1, min(int(timeout), 300)))
        after = _files(working)  # Reject links/special files before presenting any artifact.
        changed = sorted(rel for rel in after if before.get(rel) != after[rel])
        deleted = sorted(set(before) - set(after))
        result.update(exit_code=exit_code, stdout=stdout, stderr=stderr,
                      changed_files=[f'{RUNS_FOLDER}/{run_id}/working/{rel}' for rel in changed],
                      deleted_files=deleted, engine=info['engine'], image=image,
                      isolation='container', run_id=run_id,
                      message='Changes are staged in a separate task copy. Original workspace files were not mounted.')
        manifest = {**result, 'source_hashes': before, 'output_hashes': after}
        (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    except Exception as exc:
        result.update(exit_code=1, stderr=f'Isolated task failed: {exc}', changed_files=[])
    return result
