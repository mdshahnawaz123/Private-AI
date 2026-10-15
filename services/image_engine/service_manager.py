"""
Process management for local AI Studio Engine (ComfyUI on 127.0.0.1:8188).
Provides clean start, stop, and status control for both backend API and UI buttons.
"""
import os
import sys
import subprocess
import time
from typing import Optional, Dict, Any
import httpx
from loguru import logger

_owned_process = None

COMFY_DIR = os.getenv("EXPO_COMFYUI_DIR", r"C:\3EH\ComfyUI")
COMFY_PORT = int(os.getenv("EXPO_COMFYUI_PORT", "8188"))
COMFY_HOST = os.getenv("EXPO_COMFYUI_HOST", "127.0.0.1")


def is_engine_reachable(timeout_sec: float = 1.5) -> bool:
    """Check if the local ComfyUI engine is currently responding to HTTP requests."""
    try:
        from services.image_engine.comfyui_client import ComfyUIClient
        url = ComfyUIClient._validate_and_normalize_url(f"http://{COMFY_HOST}:{COMFY_PORT}")
        with httpx.Client(timeout=timeout_sec, trust_env=False) as client:
            resp = client.get(f"{url}/system_stats")
            return resp.status_code == 200
    except Exception:
        return False


def find_process_on_port(port: int = COMFY_PORT) -> Optional[int]:
    """Find the process ID listening on the engine port on Windows."""
    try:
        cmd = f'powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue).OwningProcess"'
        out = subprocess.check_output(cmd, shell=True, text=True, timeout=5).strip()
        lines = [line.strip() for line in out.splitlines() if line.strip().isdigit()]
        if lines:
            return int(lines[0])
    except Exception:
        pass
    return None


def start_engine() -> Dict[str, Any]:
    """
    Launch the ComfyUI engine process in the background if not already running.
    Redirects stdout/stderr to comfyui_server.log in the ComfyUI directory.
    """
    if is_engine_reachable():
        return {
            "status": "online",
            "available": True,
            "message": "AI Studio Engine is already running and ready.",
        }

    existing_pid = find_process_on_port(COMFY_PORT)
    if existing_pid:
        return {
            "status": "starting",
            "available": False,
            "pid": existing_pid,
            "message": f"AI Studio Engine is already initializing (PID {existing_pid}).",
        }

    venv_py = os.path.join(COMFY_DIR, "venv", "Scripts", "python.exe")
    python_exe = venv_py if os.path.isfile(venv_py) else sys.executable
    main_py = os.path.join(COMFY_DIR, "main.py")

    if not os.path.isfile(main_py):
        logger.error(f"Cannot find main.py at {COMFY_DIR}")
        return {
            "status": "error",
            "available": False,
            "message": f"Engine root directory or main.py not found at {COMFY_DIR}",
        }

    global _owned_process
    from pathlib import Path
    from services.image_engine.comfyui_client import ComfyUIClient
    try:
        ComfyUIClient._validate_and_normalize_url(f"http://{COMFY_HOST}:{COMFY_PORT}")
        log_root = Path(__file__).resolve().parents[2] / "data" / "image-engine"
        log_root.mkdir(parents=True, exist_ok=True)
        with (log_root / "comfy.stdout.log").open("ab") as stdout, (log_root / "comfy.stderr.log").open("ab") as stderr:
            _owned_process = subprocess.Popen(
                [python_exe, main_py, "--listen", COMFY_HOST, "--port", str(COMFY_PORT), "--disable-auto-launch"],
                cwd=COMFY_DIR, stdout=stdout, stderr=stderr,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"status": "starting", "available": False, "pid": _owned_process.pid,
                "message": "Local engine launched; wait for readiness."}
    except (OSError, ValueError) as exc:
        return {"status": "error", "available": False, "message": str(exc)}


def stop_engine() -> Dict[str, Any]:
    """Stop only the still-live child created by this manager, never an arbitrary port owner."""
    global _owned_process
    if _owned_process is None or _owned_process.poll() is not None:
        return {"status": "unmanaged", "available": is_engine_reachable(),
                "message": "No owned engine process to stop. Stop externally started ComfyUI from its launcher."}
    try:
        _owned_process.terminate()
        _owned_process.wait(timeout=10)
        _owned_process = None
        return {"status": "offline", "available": False, "message": "Owned engine process stopped."}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "error", "available": True, "message": str(exc)}
