import os
import sys
import unittest
import urllib.request
import urllib.error
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@unittest.skipUnless(os.getenv("EXPO_RUN_LIVE_SECURITY_TESTS") == "1", "Live server checks require explicit opt-in")
class LiveSecurityAuditTest(unittest.TestCase):
    BASE_URL = "http://127.0.0.1:8090"

    @classmethod
    def setUpClass(cls):
        cls.username = os.environ.get("EXPO_TEST_USERNAME")
        cls.password = os.environ.get("EXPO_TEST_PASSWORD")
        if not cls.username or not cls.password:
            raise unittest.SkipTest("Provide test credentials; this suite never resets account passwords")

    def setUp(self):
        login_req = urllib.request.Request(
            f"{self.BASE_URL}/auth/login",
            data=json.dumps({"username": self.username, "password": self.password}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(login_req) as resp:
            self.cookie_header = resp.headers.get("Set-Cookie", "")
            data = json.loads(resp.read().decode("utf-8"))
            self.token = data["token"]

    def test_01_http_security_headers(self):
        req = urllib.request.Request(f"{self.BASE_URL}/health")
        with urllib.request.urlopen(req) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            self.assertEqual(headers.get("x-content-type-options"), "nosniff")
            self.assertEqual(headers.get("x-frame-options"), "SAMEORIGIN")
            self.assertEqual(headers.get("referrer-policy"), "no-referrer")
            self.assertIn("geolocation=()", headers.get("permissions-policy", ""))

    def test_02_httponly_jwt_cookie(self):
        self.assertIn("httponly", self.cookie_header.lower())

    def test_03_metrics_admin_role_gating(self):
        # Unauthenticated request must receive 401
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{self.BASE_URL}/metrics")
        self.assertEqual(ctx.exception.code, 401)

        # Authenticated admin must succeed
        req = urllib.request.Request(
            f"{self.BASE_URL}/metrics",
            headers={"Authorization": f"Bearer {self.token}"}
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)

    def test_04_mpd_project_idor_protection(self):
        # Unauthenticated MPD request must receive 401
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"{self.BASE_URL}/api/v1/masterplan/projects/C3085%20-%203EH%20-Expo%20Hills/plots")
        self.assertEqual(ctx.exception.code, 401)

        # Non-existent or traversal project must receive 400 or 404
        req = urllib.request.Request(
            f"{self.BASE_URL}/api/v1/masterplan/projects/NonExistentProject/plots",
            headers={"Authorization": f"Bearer {self.token}"}
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertIn(ctx.exception.code, (400, 404))

    def test_05_unsupported_upload_format_blocked(self):
        boundary = "----TestBoundarySecurity"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="project"\r\n\r\n'
            f"C3085 - 3EH -Expo Hills\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="malicious.php"\r\n'
            f"Content-Type: application/x-php\r\n\r\n"
            f"<?php phpinfo(); ?>\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")

        req = urllib.request.Request(
            f"{self.BASE_URL}/chat/attachments",
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Authorization": f"Bearer {self.token}"
            }
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)
        err_msg = ctx.exception.read().decode("utf-8")
        self.assertIn("not allowed for security reasons", err_msg)


if __name__ == "__main__":
    unittest.main()
