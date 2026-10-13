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

COMFY_DIR = os.getenv("EXPO_COMFYUI_DIR", r"C:\3EH\ComfyUI")
COMFY_PORT = int(os.getenv("EXPO_COMFYUI_PORT", "8188"))
COMFY_HOST = os.getenv("EXPO_COMFYUI_HOST", "127.0.0.1")


def is_engine_reachable(timeout_sec: float = 1.5) -> bool:
    """Check if the local ComfyUI engine is currently responding to HTTP requests."""
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            resp = client.get(f"http://{COMFY_HOST}:{COMFY_PORT}/system_stats")
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

    log_file = os.path.join(COMFY_DIR, "comfyui_server.log")
    try:
        log_handle = open(log_file, "a", encoding="utf-8")
        log_handle.write(f"\n--- AI Studio Engine started at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log_handle.flush()
    except Exception as e:
        logger.warning(f"Failed to open comfy log file: {e}")
        log_handle = subprocess.DEVNULL

    # Windows detached background process flags
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    CREATE_NO_WINDOW = 0x08000000
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

    try:
        ps_cmd = (
            f'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command '
            f'"Start-Process -FilePath \'{python_exe}\' '
            f'-ArgumentList \'main.py --listen {COMFY_HOST} --port {COMFY_PORT} --highvram\' '
            f'-WorkingDirectory \'{COMFY_DIR}\' '
            f'-RedirectStandardOutput \'{log_file}\' '
            f'-RedirectStandardError \'{log_file}\' '
            f'-WindowStyle Hidden"'
        )
        subprocess.run(ps_cmd, shell=True, check=True, timeout=10)
        logger.info(f"Launched AI Studio Engine via Start-Process at {COMFY_DIR}")
        return {
            "status": "starting",
            "available": False,
            "message": "AI Studio Engine launched. Please wait a few seconds for initialization.",
        }
    except Exception as exc:
        logger.error(f"Failed to launch AI Studio Engine: {exc}")
        return {
            "status": "error",
            "available": False,
            "message": f"Failed to start engine: {exc}",
        }


def stop_engine() -> Dict[str, Any]:
    """
    Cleanly terminate the ComfyUI engine process tree and release the port.
    """
    pid = find_process_on_port(COMFY_PORT)
    if not pid:
        if not is_engine_reachable():
            return {
                "status": "offline",
                "available": False,
                "message": "AI Studio Engine is already stopped.",
            }

    try:
        if pid:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
            logger.info(f"Terminated AI Studio Engine process PID={pid}")
        else:
            # Fallback stop by port if PID wasn't found directly
            kill_cmd = f'powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort {COMFY_PORT} -State Listen -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force }}"'
            subprocess.run(kill_cmd, shell=True, capture_output=True, check=False)

        # Wait briefly for port release
        time.sleep(0.5)
        return {
            "status": "offline",
            "available": False,
            "message": "AI Studio Engine stopped successfully.",
        }
    except Exception as exc:
        logger.error(f"Failed to stop AI Studio Engine: {exc}")
        return {
            "status": "error",
            "available": False,
            "message": f"Failed to stop engine: {exc}",
        }
