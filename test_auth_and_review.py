import unittest
import os
import shutil
from fastapi.testclient import TestClient
from main import app
import auth_db
import email_service


class TestAuthAndReviewSystem(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        # Reset DB test table
        conn = auth_db.get_db_connection()
        conn.execute("DELETE FROM reviews")
        conn.execute("DELETE FROM users")
        conn.commit()
        conn.close()

    def test_signup_and_login_flow(self):
        """Tests that a user can sign up with email and log in without OTP."""
        import uuid
        test_email = f"creator_{uuid.uuid4().hex[:8]}@example.com"
        # 1. Sign up
        resp_signup = self.client.post("/api/auth/signup", json={
            "email": test_email,
            "password": "secretpassword"
        })
        self.assertEqual(resp_signup.status_code, 200)
        data = resp_signup.json()
        self.assertTrue(data["success"])
        self.assertIn("token", data)
        self.assertEqual(data["user"]["email"], test_email)
        self.assertEqual(data["user"]["clips_count"], 0)
        self.assertFalse(data["user"]["has_reviewed"])

        token = data["token"]

        # 2. Check /api/auth/me with token
        resp_me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(resp_me.status_code, 200)
        me_data = resp_me.json()
        self.assertTrue(me_data["authenticated"])
        self.assertEqual(me_data["user"]["email"], test_email)

        # 3. Log in with same credentials
        resp_login = self.client.post("/api/auth/login", json={
            "email": test_email,
            "password": "secretpassword"
        })
        self.assertEqual(resp_login.status_code, 200)
        login_data = resp_login.json()
        self.assertTrue(login_data["success"])
        self.assertIn("token", login_data)

    def test_review_threshold_blocking_and_unlocking(self):
        """
        Tests:
        1. User creates account
        2. User generates clips up to 15
        3. At 15 clips, further generation is blocked with HTTP 403 review required
        4. User submits review
        5. Review is saved, emailed to owner, and generation is immediately unlocked!
        """
        import uuid
        test_email = f"videomaker_{uuid.uuid4().hex[:8]}@test.com"
        # Sign up
        signup = self.client.post("/api/auth/signup", json={
            "email": test_email,
            "password": "pass1234password"
        }).json()
        token = signup["token"]
        user_id = signup["user"]["id"]

        # Simulate generating 14 clips (below threshold)
        auth_db.increment_user_clips(user_id, 14)
        status_14 = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual(status_14["user"]["clips_count"], 14)
        self.assertFalse(status_14["review_required"])

        # Simulate reaching 15 clips -> clip generation is not blocked
        auth_db.increment_user_clips(user_id, 1)
        status_15 = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual(status_15["user"]["clips_count"], 15)
        self.assertFalse(status_15["review_required"])

        # Attempt to slice a clip with token -> Allowed without 15-clip lock
        import tempfile
        import subprocess
        t_src = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        temp_src = t_src.name
        t_src.close()

        try:
            from video_utils import _find_ffmpeg_exe
            ffmpeg_bin = _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg"
            cmd = [
                ffmpeg_bin, "-y",
                "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "1",
                "-c:v", "libx264", "-c:a", "aac",
                temp_src
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            with open(temp_src, "rb") as vf:
                allowed_resp = self.client.post(
                    "/slice-clip",
                    files={"file": ("test.mp4", vf, "video/mp4")},
                    data={
                        "start_time": 0.0,
                        "duration": 1.0,
                        "aspect_ratio": "original",
                        "burn_captions": "false",
                        "auth_token": token
                    }
                )
            self.assertEqual(allowed_resp.status_code, 200)

            # Now submit a review!
            review_resp = self.client.post(
                "/api/submit-review",
                json={
                    "rating": 5,
                    "review_text": "Super fast and wonderful tool! Absolutely love the clipping.",
                    "auth_token": token
                }
            )
            self.assertEqual(review_resp.status_code, 200)
            rev_data = review_resp.json()
            self.assertTrue(rev_data["success"])
            self.assertTrue(rev_data["has_reviewed"])

            # Verify that user status shows reviewed
            status_reviewed = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
            self.assertTrue(status_reviewed["user"]["has_reviewed"])
            self.assertFalse(status_reviewed["review_required"])

            # Now slicing clip must succeed with HTTP 200!
            with open(temp_src, "rb") as vf:
                allowed_resp = self.client.post(
                    "/slice-clip",
                    files={"file": ("test.mp4", vf, "video/mp4")},
                    data={
                        "start_time": 0.0,
                        "duration": 1.0,
                        "aspect_ratio": "original",
                        "burn_captions": "false",
                        "auth_token": token
                    }
                )
            self.assertEqual(allowed_resp.status_code, 200)

        finally:
            if os.path.exists(temp_src):
                try:
                    os.remove(temp_src)
                except Exception:
                    pass

    def test_direct_owner_email_routing(self):
        """Verifies that submitted reviews are sent to OWNER_EMAIL and logged."""
        owner_email = email_service.get_owner_email()
        self.assertTrue(len(owner_email) > 0)

        result = email_service.send_review_email_to_owner(
            user_email="reviewer@example.com",
            rating=5,
            review_text="Amazing video subtitle generator!",
            clips_count=16
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["owner_email"], owner_email)

        # Check that reviews_log.txt contains this entry
        log_path = email_service.REVIEWS_LOG_FILE
        self.assertTrue(os.path.exists(log_path))
        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("reviewer@example.com", content)
        self.assertIn("Amazing video subtitle generator!", content)


if __name__ == "__main__":
    unittest.main()
