"""
Unit tests for ComfyUI async client with mocked HTTP and WebSocket transports.
"""

import asyncio
import io
import json
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

import httpx
from PIL import Image

from services.image_engine.comfyui_client import (
    ComfyUIClient,
    ComfyUIConnectionError,
    ComfyUIValidationError,
    ComfyUIExecutionError,
    ComfyUIOutOfMemoryError,
    ComfyUITimeoutError,
    ComfyUIInterruptedError,
)


class TestComfyUIClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = ComfyUIClient(base_url="http://127.0.0.1:8188", timeout=5.0)

    def test_security_localhost_validation(self):
        # Valid local endpoints
        ComfyUIClient("http://127.0.0.1:8188")
        ComfyUIClient("http://localhost:8188")

        # Invalid external endpoints must be blocked
        with self.assertRaises(ValueError):
            ComfyUIClient("http://192.168.1.100:8188")
        with self.assertRaises(ValueError):
            ComfyUIClient("https://api.external-inference.com")

    async def test_check_health_when_offline_returns_available_false(self):
        with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
            status = await self.client.check_health()
            self.assertFalse(status.available)
            self.assertIn("unreachable", status.details.lower())

    async def test_check_health_when_online_parses_metrics(self):
        mock_stats = {
            "devices": [{
                "name": "NVIDIA GeForce RTX 5080",
                "type": "cuda",
                "vram_total": 16 * 1024 * 1024 * 1024,
                "vram_free": 12 * 1024 * 1024 * 1024,
            }]
        }
        mock_queue = {"queue_running": [], "queue_pending": [{"id": 1}]}

        def mock_get(url, **kwargs):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            if "system_stats" in str(url):
                mock_resp.json.return_value = mock_stats
            elif "queue" in str(url):
                mock_resp.json.return_value = mock_queue
            return mock_resp

        with patch("httpx.AsyncClient.get", new=AsyncMock(side_effect=mock_get)):
            status = await self.client.check_health()
            self.assertTrue(status.available)
            self.assertEqual(status.device, "NVIDIA GeForce RTX 5080")
            self.assertEqual(status.vram_total_mb, 16384)
            self.assertEqual(status.vram_free_mb, 12288)
            self.assertEqual(status.queue_pending, 1)

    async def test_submit_prompt_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"prompt_id": "test-prompt-123", "number": 1}

        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            res = await self.client.submit_prompt({"1": {"class_type": "SaveImage", "inputs": {}}})
            self.assertEqual(res["prompt_id"], "test-prompt-123")

    async def test_submit_prompt_validation_error_on_400(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Node configuration error"
        mock_resp.json.return_value = {"node_errors": {"5": "Missing input: seed"}}

        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_resp)):
            with self.assertRaises(ComfyUIValidationError) as ctx:
                await self.client.submit_prompt({"1": {"class_type": "KSampler", "inputs": {}}})
            self.assertIn("Missing input: seed", str(ctx.exception))

    async def test_get_image_bytes_validates_image_content(self):
        # Generate genuine small 64x64 PNG in memory
        buf = io.BytesIO()
        img = Image.new("RGB", (64, 64), color="blue")
        img.save(buf, format="PNG")
        valid_png_bytes = buf.getvalue()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = valid_png_bytes

        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
            content = await self.client.get_image_bytes("concept_001.png")
            self.assertEqual(content, valid_png_bytes)

    async def test_get_image_bytes_rejects_corrupted_payload(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"NOT_A_VALID_IMAGE_DATA_12345"

        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=mock_resp)):
            with self.assertRaises(Exception) as ctx:
                await self.client.get_image_bytes("corrupted.png")
            self.assertIn("corrupted", str(ctx.exception).lower())

    async def test_track_execution_websocket_oom_interception(self):
        prompt_id = "oom-prompt-123"
        client_id = "test-client"

        # Mock WebSocket messages simulating progress then CUDA OOM error
        class MockWs:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def recv(self):
                return json.dumps({
                    "type": "execution_error",
                    "data": {
                        "prompt_id": prompt_id,
                        "exception_type": "OutOfMemoryError",
                        "exception_message": "CUDA out of memory. Tried to allocate 4.20 GiB",
                    }
                })

        with patch("websockets.connect", return_value=MockWs()):
            with self.assertRaises(ComfyUIOutOfMemoryError) as ctx:
                await self.client._track_via_websocket("ws://127.0.0.1:8188/ws", prompt_id, None)
            self.assertIn("CUDA Out Of Memory", str(ctx.exception))

    async def test_track_execution_websocket_success_and_progress(self):
        prompt_id = "success-prompt-123"
        messages = [
            json.dumps({"type": "progress", "data": {"prompt_id": prompt_id, "value": 10, "max": 20}}),
            json.dumps({"type": "executing", "data": {"prompt_id": prompt_id, "node": None}}),
        ]

        class MockWs:
            def __init__(self):
                self._msgs = list(messages)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def recv(self):
                if self._msgs:
                    return self._msgs.pop(0)
                await asyncio.sleep(1)

        progress_recorded = []
        def on_progress(val, total):
            progress_recorded.append((val, total))

        mock_history = {
            "outputs": {
                "7": {"images": [{"filename": "out_001.png", "subfolder": "", "type": "output"}]}
            }
        }

        with patch("websockets.connect", return_value=MockWs()):
            with patch.object(self.client, "get_history", new=AsyncMock(return_value=mock_history)):
                outputs = await self.client._track_via_websocket("ws://127.0.0.1:8188/ws", prompt_id, on_progress)
                self.assertIn("7", outputs)
                self.assertEqual(progress_recorded, [(10, 20)])


if __name__ == "__main__":
    unittest.main()
