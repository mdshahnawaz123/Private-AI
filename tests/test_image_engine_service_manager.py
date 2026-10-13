import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import auth
from main import app
from services.image_engine import service_manager


class TestImageEngineServiceManager(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.auth_token = auth.make_token({"id": 1, "username": "admin", "role": "admin"})
        self.auth_headers = {"Authorization": f"Bearer {self.auth_token}"}

    @patch("services.image_engine.service_manager.httpx.Client")
    def test_is_engine_reachable_true(self, mock_client_cls):
        mock_resp = MagicMock(status_code=200)
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        self.assertTrue(service_manager.is_engine_reachable())

    @patch("services.image_engine.service_manager.httpx.Client")
    def test_is_engine_reachable_false_on_error(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        self.assertFalse(service_manager.is_engine_reachable())

    @patch("services.image_engine.service_manager.is_engine_reachable", return_value=True)
    def test_start_engine_already_running(self, mock_reachable):
        res = service_manager.start_engine()
        self.assertEqual(res["status"], "online")
        self.assertTrue(res["available"])

    @patch("services.image_engine.service_manager.find_process_on_port", return_value=None)
    @patch("services.image_engine.service_manager.is_engine_reachable", return_value=False)
    def test_stop_engine_already_offline(self, mock_reachable, mock_pid):
        res = service_manager.stop_engine()
        self.assertEqual(res["status"], "offline")
        self.assertFalse(res["available"])

    @patch("services.image_engine.service_manager.start_engine")
    def test_api_service_start_endpoint(self, mock_start):
        mock_start.return_value = {"status": "starting", "available": False, "message": "Starting"}
        resp = self.client.post("/api/image-engine/service/start", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "starting")

    @patch("services.image_engine.service_manager.stop_engine")
    def test_api_service_stop_endpoint(self, mock_stop):
        mock_stop.return_value = {"status": "offline", "available": False, "message": "Stopped"}
        resp = self.client.post("/api/image-engine/service/stop", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "offline")

    @patch("services.image_engine.service_manager.is_engine_reachable", return_value=True)
    def test_api_service_status_endpoint(self, mock_reachable):
        resp = self.client.get("/api/image-engine/service/status", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["available"])
        self.assertEqual(resp.json()["status"], "online")


if __name__ == "__main__":
    unittest.main()
