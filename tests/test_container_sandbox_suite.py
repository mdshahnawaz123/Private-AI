"""
Unit tests for Container Sandbox (Option B)
Tests engine discovery, fail-closed isolation policies, and Cowork integration.
"""
import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from services.container_sandbox import (
    find_container_engine,
    get_container_image,
    run_code_in_container,
    SANDBOX_IMAGE_NAME,
    FALLBACK_IMAGE_NAME
)
from services.cowork_workspace import run_workspace_python


class TestContainerSandbox(unittest.TestCase):

    def test_find_container_engine_structure(self):
        """Engine discovery must always return structured status with expected keys."""
        status = find_container_engine()
        self.assertIsInstance(status, dict)
        self.assertIn("available", status)
        self.assertIn("engine", status)
        self.assertIn("daemon_running", status)
        self.assertIn("message", status)

    @patch("services.container_sandbox.shutil.which", return_value=None)
    @patch("services.container_sandbox.os.path.isfile", return_value=False)
    def test_find_container_engine_not_installed(self, mock_isfile, mock_which):
        """When neither Docker nor Podman is present, return available=False with install guide."""
        status = find_container_engine()
        self.assertFalse(status["available"])
        self.assertFalse(status["daemon_running"])
        self.assertIsNone(status["engine"])
        self.assertIn("Docker Desktop", status["message"])

    @patch("services.container_sandbox.shutil.which", return_value="C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe")
    @patch("services.container_sandbox.subprocess.run")
    def test_find_container_engine_installed_daemon_offline(self, mock_run, mock_which):
        """When docker.exe exists but daemon is offline, return available=True, daemon_running=False."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "error during connect"
        mock_run.return_value = mock_proc

        status = find_container_engine()
        self.assertTrue(status["available"])
        self.assertFalse(status["daemon_running"])
        self.assertEqual(status["engine"], "docker")
        self.assertEqual(status["error_kind"], "unreachable")

    @patch("services.container_sandbox.shutil.which", return_value="C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe")
    @patch("services.container_sandbox.subprocess.run")
    def test_find_container_engine_installed_daemon_online(self, mock_run, mock_which):
        """When docker.exe exists and daemon responds, return available=True, daemon_running=True."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "27.0.3\n"
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        status = find_container_engine()
        self.assertTrue(status["available"])
        self.assertTrue(status["daemon_running"])
        self.assertEqual(status["version"], "27.0.3")

    @patch("services.container_sandbox.subprocess.run")
    def test_get_container_image_fallback(self, mock_run):
        """When custom image is not found, fallback to python:3.12-slim."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_run.return_value = mock_proc

        with self.assertRaises(RuntimeError):
            get_container_image("docker")

    @patch("services.container_sandbox.subprocess.run")
    def test_get_container_image_custom(self, mock_run):
        """When custom image exists, use expodesignai-sandbox:latest."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        img = get_container_image("docker")
        self.assertEqual(img, SANDBOX_IMAGE_NAME)

    @patch("services.container_sandbox.find_container_engine")
    def test_run_code_fails_closed_when_engine_unavailable(self, mock_find):
        """Executing code without container engine must fail closed with exit_code=1."""
        mock_find.return_value = {
            "available": False,
            "engine": None,
            "path": None,
            "daemon_running": False,
            "message": "Docker not installed"
        }
        res = run_code_in_container("print(1+1)", Path("."))
        self.assertEqual(res["exit_code"], 1)
        self.assertEqual(res["stdout"], "")
        self.assertEqual(res["stderr"], "Docker not installed")

    @patch("services.container_sandbox.find_container_engine")
    def test_cowork_workspace_fails_closed_without_os_boundary(self, mock_find):
        """Cowork run_workspace_python must refuse arbitrary code execution without OS container boundary."""
        mock_find.return_value = {
            "available": False,
            "engine": None,
            "path": None,
            "daemon_running": False,
            "message": "Docker not installed"
        }
        # Ensure test environment doesn't have override env
        old_env = os.environ.pop("EXPO_ALLOW_INSECURE_LOCAL_PYTHON", None)
        try:
            res = run_workspace_python(Path("."), "import os; print(os.getcwd())")
            self.assertEqual(res["exit_code"], 1)
            self.assertEqual(res["stderr"], "Docker not installed")
        finally:
            if old_env is not None:
                os.environ["EXPO_ALLOW_INSECURE_LOCAL_PYTHON"] = old_env


if __name__ == "__main__":
    unittest.main()
