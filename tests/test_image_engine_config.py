"""
Unit tests for ComfyUI Image Engine configuration and role resolution.
"""

import unittest
from config import Settings, get_settings, resolve_role


class TestImageEngineConfig(unittest.TestCase):
    def test_default_comfyui_settings(self):
        s = Settings()
        self.assertEqual(s.comfyui_base_url, "http://127.0.0.1:8188")
        self.assertEqual(s.image_engine_concurrency, 1)
        self.assertEqual(s.comfyui_timeout, 300.0)
        self.assertEqual(s.comfyui_connect_timeout, 3.0)
        self.assertEqual(s.image_engine_min_resolution, 512)
        self.assertEqual(s.image_engine_max_resolution, 1024)

    def test_resolve_role_render(self):
        resolved = resolve_role("render")
        self.assertIn("model", resolved)
        self.assertIn("provider", resolved)
        self.assertIn("base_url", resolved)
        self.assertEqual(resolved["base_url"], "http://127.0.0.1:8188")
        self.assertEqual(resolved["concurrency"], 1)
        self.assertEqual(resolved["timeout"], 300.0)

    def test_custom_comfyui_host_resolution(self):
        s = Settings(comfyui_base_url="http://127.0.0.1:8288/")
        self.assertEqual(s.comfyui_base_url, "http://127.0.0.1:8288/")


if __name__ == "__main__":
    unittest.main()
