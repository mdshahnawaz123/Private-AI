import unittest
import secrets
from fastapi.testclient import TestClient
from main import app
import auth
import db

class TestProfileAndCredentialsAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.client = TestClient(app)

    def test_update_profile_api(self):
        # 1. Create a test user
        uname = f"apiuser_{secrets.token_hex(4)}"
        pw = "InitialPass123!"
        u = db.create_user(uname, auth.hash_password(pw), role="user", full_name="API User")
        uid = u["id"]

        try:
            # 2. Login to get token
            login_resp = self.client.post("/auth/login", json={"username": uname, "password": pw})
            self.assertEqual(login_resp.status_code, 200)
            data = login_resp.json()
            token = data["token"]

            # 3. Try update profile with WRONG old password -> should fail (400)
            bad_pw_resp = self.client.post(
                "/auth/update-profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"old_password": "WrongPassword!", "new_username": f"new_{uname}"}
            )
            self.assertEqual(bad_pw_resp.status_code, 400)
            self.assertIn("Current password is incorrect", bad_pw_resp.json()["detail"])

            # 4. Update username with CORRECT old password
            new_uname = f"renamed_{secrets.token_hex(4)}"
            upd_resp = self.client.post(
                "/auth/update-profile",
                headers={"Authorization": f"Bearer {token}"},
                json={"old_password": pw, "new_username": new_uname}
            )
            self.assertEqual(upd_resp.status_code, 200)
            upd_data = upd_resp.json()
            self.assertEqual(upd_data["status"], "ok")
            self.assertEqual(upd_data["user"]["username"], new_uname)
            new_token = upd_data["token"]
            self.assertIsNotNone(new_token)

            # 5. Verify the old token is invalidated (due to auth_version increment)
            old_tok_resp = self.client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(old_tok_resp.status_code, 401)

            # 6. Verify the new token works
            new_tok_resp = self.client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
            self.assertEqual(new_tok_resp.status_code, 200)
            self.assertEqual(new_tok_resp.json()["user"]["username"], new_uname)

            # 7. Update password via /auth/update-profile
            newer_pw = "NewSecretPass789!"
            pw_upd_resp = self.client.post(
                "/auth/update-profile",
                headers={"Authorization": f"Bearer {new_token}"},
                json={"old_password": pw, "new_password": newer_pw}
            )
            self.assertEqual(pw_upd_resp.status_code, 200)
            latest_token = pw_upd_resp.json()["token"]

            # 8. Test forced password change endpoint with new_username
            forced_uname = f"forced_{secrets.token_hex(4)}"
            final_pw = "FinalSecretPass000!"
            forced_resp = self.client.post(
                "/auth/change-password",
                headers={"Authorization": f"Bearer {latest_token}"},
                json={"old_password": newer_pw, "new_password": final_pw, "new_username": forced_uname}
            )
            self.assertEqual(forced_resp.status_code, 200)
            self.assertEqual(forced_resp.json()["user"]["username"], forced_uname)
            final_token = forced_resp.json()["token"]

            # 9. Test login with newest credentials
            final_login = self.client.post("/auth/login", json={"username": forced_uname, "password": final_pw})
            self.assertEqual(final_login.status_code, 200)

        finally:
            with db.SessionLocal() as s:
                row = s.get(db.User, uid)
                if row:
                    s.delete(row)
                    s.commit()

if __name__ == '__main__':
    unittest.main()
