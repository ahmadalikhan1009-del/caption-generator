import unittest
import uuid
import io
from fastapi.testclient import TestClient
import main
import auth_db

class TestSecurityVuln4SessionLogout(unittest.TestCase):
    """
    Automated security verification for Vulnerability #4:
    Broken Session Management & Logout Token Invalidation.
    """

    def setUp(self):
        self.client = TestClient(main.app)

    def test_01_logout_invalidates_token_completely(self):
        """After logging out, the session token cannot be reused for API operations."""
        email = f"logout_sec_{uuid.uuid4().hex[:8]}@example.com"
        reg = self.client.post("/api/auth/signup", json={"email": email, "password": "secure_password_123"}).json()
        token = reg["token"]

        # 1. Verify token is active
        me_before = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertTrue(me_before["authenticated"])

        # 2. Call logout
        logout_res = self.client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(logout_res.status_code, 200)

        # 3. Verify /api/auth/me no longer accepts the old token
        me_after = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertFalse(me_after["authenticated"])

        # 4. Verify processing endpoint rejects logged-out token with 401
        dummy_file = io.BytesIO(b"fake video data")
        res_reject = self.client.post(
            "/slice-clip",
            files={"file": ("test.mp4", dummy_file, "video/mp4")},
            data={
                "start_time": 0.0,
                "duration": 1.0,
                "aspect_ratio": "original",
                "burn_captions": "false",
                "auth_token": token
            }
        )
        self.assertEqual(res_reject.status_code, 401)
        self.assertIn("Session expired or invalid login", res_reject.json()["detail"])

if __name__ == "__main__":
    unittest.main()
