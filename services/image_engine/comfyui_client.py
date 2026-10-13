"""
Asynchronous HTTP and WebSocket client for locally hosted ComfyUI service.

Enforces offline operation, localhost binding, and timeout boundaries.
Provides resilient tracking of workflow execution via WebSocket event streaming
with polling fallback on connection interruptions.
"""

import asyncio
import io
import json
import uuid
from typing import Dict, Any, Optional, Callable, List
from urllib.parse import urlparse

import httpx
import websockets
from loguru import logger
from PIL import Image

from services.image_engine.schemas import EngineStatus


class ComfyUIError(RuntimeError):
    """Base exception for all ComfyUI client errors."""
    pass


class ComfyUIConnectionError(ComfyUIError):
    """Raised when ComfyUI service is unreachable."""
    pass


class ComfyUIValidationError(ComfyUIError):
    """Raised when workflow JSON or prompt parameters are rejected by ComfyUI."""
    pass


class ComfyUIExecutionError(ComfyUIError):
    """Raised when a ComfyUI node execution fails."""
    pass


class ComfyUIOutOfMemoryError(ComfyUIExecutionError):
    """Raised specifically when a CUDA Out Of Memory error is intercepted."""
    pass


class ComfyUIInterruptedError(ComfyUIError):
    """Raised when workflow execution is cancelled or interrupted."""
    pass


class ComfyUITimeoutError(ComfyUIError):
    """Raised when generation exceeds the configured deadline."""
    pass


class ComfyUIClient:
    """
    Client for interacting with local ComfyUI instance on localhost:8188.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8188",
        timeout: float = 300.0,
        connect_timeout: float = 3.0,
        ws_timeout: float = 300.0,
    ):
        self.base_url = self._validate_and_normalize_url(base_url)
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.ws_timeout = ws_timeout
        self._cached_object_info: Optional[Dict[str, Any]] = None

    @staticmethod
    def _validate_and_normalize_url(url: str) -> str:
        """Validate URL is bound to localhost/127.0.0.1 to prevent external network leakage."""
        clean = url.rstrip("/")
        parsed = urlparse(clean)
        hostname = (parsed.hostname or "").lower()
        if hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(
                f"Security violation: ComfyUI must be bound to localhost (got {hostname!r})"
            )
        return clean

    @property
    def ws_url(self) -> str:
        """Derive WebSocket endpoint URL from the HTTP base URL."""
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return f"{scheme}://{parsed.netloc}/ws"

    async def check_health(self) -> EngineStatus:
        """
        Check if ComfyUI is reachable and report GPU memory and queue metrics.
        Returns EngineStatus with available=False on connection error (never throws).
        """
        try:
            fast_timeout = httpx.Timeout(2.0, connect=0.5)
            async with httpx.AsyncClient(timeout=fast_timeout) as client:
                resp = await client.get(f"{self.base_url}/system_stats")
                if resp.status_code != 200:
                    return EngineStatus(
                        available=False,
                        base_url=self.base_url,
                        details=f"ComfyUI returned HTTP {resp.status_code}",
                    )
                data = resp.json()

                # Also check queue depth
                q_resp = await client.get(f"{self.base_url}/queue")
                q_data = q_resp.json() if q_resp.status_code == 200 else {}
                running_count = len(q_data.get("queue_running", []))
                pending_count = len(q_data.get("queue_pending", []))

                devices = data.get("devices", [])
                primary = devices[0] if devices else {}
                vram_total = primary.get("vram_total")
                vram_free = primary.get("vram_free")

                return EngineStatus(
                    available=True,
                    base_url=self.base_url,
                    device=primary.get("name", "NVIDIA RTX GPU"),
                    vram_total_mb=int(vram_total / (1024 * 1024)) if vram_total else None,
                    vram_free_mb=int(vram_free / (1024 * 1024)) if vram_free else None,
                    queue_running=running_count,
                    queue_pending=pending_count,
                    details="ComfyUI is ready for local inference",
                )
        except Exception as exc:
            return EngineStatus(
                available=False,
                base_url=self.base_url,
                details=f"ComfyUI unreachable: {str(exc)}",
            )

    async def get_object_info(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Retrieve available node specifications and input definitions.
        Cached in memory after initial call.
        """
        if self._cached_object_info is not None and not force_refresh:
            return self._cached_object_info

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/object_info")
                if resp.status_code != 200:
                    raise ComfyUIConnectionError(
                        f"Failed to fetch object_info from ComfyUI: HTTP {resp.status_code}"
                    )
                self._cached_object_info = resp.json()
                return self._cached_object_info
        except httpx.RequestError as exc:
            raise ComfyUIConnectionError(f"Could not connect to ComfyUI on {self.base_url}: {exc}") from exc

    async def submit_prompt(self, workflow: Dict[str, Any], client_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Submit a validated Prompt API format workflow dictionary to ComfyUI.
        Returns {'prompt_id': str, 'number': int, 'node_errors': dict}.
        """
        cid = client_id or uuid.uuid4().hex
        payload = {"prompt": workflow, "client_id": cid}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{self.base_url}/prompt", json=payload)
                if resp.status_code == 400:
                    err_body = resp.text
                    try:
                        err_json = resp.json()
                        node_errors = err_json.get("node_errors", {})
                        if node_errors:
                            err_body = f"Node configuration errors: {json.dumps(node_errors)}"
                    except Exception:
                        pass
                    raise ComfyUIValidationError(f"Workflow rejected by ComfyUI (HTTP 400): {err_body}")
                elif resp.status_code != 200:
                    raise ComfyUIError(f"ComfyUI /prompt returned HTTP {resp.status_code}: {resp.text}")

                res_json = resp.json()
                prompt_id = res_json.get("prompt_id")
                if not prompt_id:
                    raise ComfyUIError(f"Malformed ComfyUI response (missing prompt_id): {res_json}")
                return res_json
        except httpx.RequestError as exc:
            raise ComfyUIConnectionError(f"Failed to submit prompt to ComfyUI: {exc}") from exc

    async def get_history(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        """Fetch execution history and generated image references for a prompt ID."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.base_url}/history/{prompt_id}")
                if resp.status_code != 200:
                    return None
                data = resp.json()
                return data.get(prompt_id)
        except Exception as exc:
            logger.debug(f"History poll error for {prompt_id}: {exc}")
            return None

    async def get_image_bytes(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        """
        Retrieve generated image bytes from ComfyUI /view endpoint.
        Validates that returned bytes represent a genuine image format.
        """
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{self.base_url}/view", params=params)
                if resp.status_code != 200:
                    raise ComfyUIError(f"Failed to retrieve image {filename!r}: HTTP {resp.status_code}")
                content = resp.content
                if not content:
                    raise ComfyUIError(f"Retrieved image {filename!r} is empty (0 bytes)")

                # Verify valid image payload
                try:
                    img = Image.open(io.BytesIO(content))
                    img.verify()
                except Exception as img_err:
                    raise ComfyUIError(
                        f"Retrieved image {filename!r} contains corrupted image data: {img_err}"
                    ) from img_err

                return content
        except httpx.RequestError as exc:
            raise ComfyUIConnectionError(f"Failed to fetch image from ComfyUI: {exc}") from exc

    async def upload_image(self, image_bytes: bytes, filename: str, overwrite: bool = True) -> Dict[str, Any]:
        """Upload input image (sketch / render) to ComfyUI input directory."""
        files = {"image": (filename, image_bytes, "image/png")}
        data = {"overwrite": "true" if overwrite else "false"}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{self.base_url}/upload/image", files=files, data=data)
                if resp.status_code != 200:
                    raise ComfyUIError(f"Failed to upload image to ComfyUI: HTTP {resp.status_code} {resp.text}")
                return resp.json()
        except httpx.RequestError as exc:
            raise ComfyUIConnectionError(f"Could not upload image to ComfyUI: {exc}") from exc

    async def interrupt(self) -> bool:
        """Send interrupt signal to cancel active prompt execution."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(f"{self.base_url}/interrupt")
                return resp.status_code == 200
        except Exception:
            return False

    async def track_execution(
        self,
        prompt_id: str,
        client_id: str,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Track workflow execution via WebSocket event stream.
        Falls back to history polling if WebSocket is unavailable.
        Returns final execution outputs dictionary.
        """
        max_duration = timeout or self.timeout
        ws_endpoint = f"{self.ws_url}?clientId={client_id}"

        try:
            return await asyncio.wait_for(
                self._track_via_websocket(ws_endpoint, prompt_id, progress_cb),
                timeout=max_duration,
            )
        except (websockets.exceptions.WebSocketException, OSError, asyncio.TimeoutError) as ws_err:
            if isinstance(ws_err, asyncio.TimeoutError):
                raise ComfyUITimeoutError(
                    f"Generation timed out after {max_duration} seconds for prompt {prompt_id}"
                ) from ws_err

            logger.warning(
                f"WebSocket connection failed ({ws_err}); falling back to HTTP history polling for {prompt_id}"
            )
            return await self._poll_history_fallback(prompt_id, progress_cb, max_duration)

    async def _track_via_websocket(
        self,
        ws_endpoint: str,
        prompt_id: str,
        progress_cb: Optional[Callable[[int, int], None]],
    ) -> Dict[str, Any]:
        """Internal WebSocket event listener loop."""
        async with websockets.connect(ws_endpoint) as ws:
            while True:
                msg_raw = await ws.recv()
                if isinstance(msg_raw, bytes):
                    # Preview binary image frames, ignore in raw loop
                    continue

                try:
                    event = json.loads(msg_raw)
                except Exception:
                    continue

                msg_type = event.get("type")
                data = event.get("data", {})

                if msg_type == "progress":
                    if data.get("prompt_id") == prompt_id:
                        val = data.get("value", 0)
                        max_val = data.get("max", 1)
                        if progress_cb and max_val > 0:
                            progress_cb(val, max_val)

                elif msg_type == "execution_error":
                    if data.get("prompt_id") == prompt_id:
                        exc_msg = data.get("exception_message", "Unknown error")
                        exc_type = data.get("exception_type", "")
                        if "OutOfMemoryError" in exc_type or "CUDA out of memory" in exc_msg:
                            raise ComfyUIOutOfMemoryError(
                                f"CUDA Out Of Memory in ComfyUI: {exc_msg}. "
                                "Suggestion: Reduce resolution or close competing GPU workloads."
                            )
                        raise ComfyUIExecutionError(f"Node execution error ({exc_type}): {exc_msg}")

                elif msg_type == "execution_interrupted":
                    if data.get("prompt_id") == prompt_id:
                        raise ComfyUIInterruptedError(f"Execution was interrupted for prompt {prompt_id}")

                elif msg_type == "executing":
                    if data.get("prompt_id") == prompt_id and data.get("node") is None:
                        # Node is null indicates the entire workflow has finished execution
                        break

        # Finished via WebSocket -> Retrieve final image references from history
        history = await self.get_history(prompt_id)
        if not history:
            raise ComfyUIError(f"Execution completed but history was not found for prompt {prompt_id}")
        return history.get("outputs", {})

    async def _poll_history_fallback(
        self,
        prompt_id: str,
        progress_cb: Optional[Callable[[int, int], None]],
        timeout: float,
    ) -> Dict[str, Any]:
        """Polls history endpoint when WebSocket stream is unavailable."""
        start_time = asyncio.get_event_loop().time()
        poll_interval = 1.0

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            history = await self.get_history(prompt_id)
            if history:
                status = history.get("status", {})
                for msg in status.get("messages", []):
                    if msg and msg[0] == "execution_error":
                        raise ComfyUIExecutionError(f"Execution error from history: {msg[1]}")
                if status.get("completed", False) or status.get("status_str") == "success" or bool(history.get("outputs")):
                    if progress_cb:
                        progress_cb(100, 100)
                    return history.get("outputs", {})

            await asyncio.sleep(poll_interval)

        raise ComfyUITimeoutError(f"Generation timed out after {timeout}s polling prompt {prompt_id}")
