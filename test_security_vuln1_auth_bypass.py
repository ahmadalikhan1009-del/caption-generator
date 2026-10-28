import os
import unittest
import tempfile
import subprocess
import uuid
from fastapi.testclient import TestClient
import main
import auth_db

class TestSecurityVuln1AuthBypass(unittest.TestCase):
    """
    Automated security verification for Vulnerability #1:
    Authentication and 5-Video Gate Bypass Prevention.
    Verifies that all processing endpoints strictly require valid authentication (HTTP 401),
    and strictly enforce the 5-video review policy (HTTP 403).
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.test_dir = tempfile.mkdtemp()
        cls.dummy_video_path = os.path.join(cls.test_dir, "sec_test.mp4")

        from video_utils import _find_ffmpeg_exe
        ffmpeg_bin = _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg"
        cmd = [
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "1",
            "-c:v", "libx264", "-c:a", "aac",
            cls.dummy_video_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        import shutil
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_upload_without_auth_rejected_401(self):
        """POST /upload without auth must return 401."""
        with open(self.dummy_video_path, "rb") as f:
            res = self.client.post("/upload", files={"file": ("sec.mp4", f, "video/mp4")})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication required", res.json()["detail"])

    def test_02_extract_clips_without_auth_rejected_401(self):
        """POST /extract-clips without auth must return 401."""
        with open(self.dummy_video_path, "rb") as f:
            res = self.client.post("/extract-clips", files={"file": ("sec.mp4", f, "video/mp4")})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication required", res.json()["detail"])

    def test_03_slice_clip_without_auth_rejected_401(self):
        """POST /slice-clip without auth must return 401."""
        with open(self.dummy_video_path, "rb") as f:
            res = self.client.post("/slice-clip", files={"file": ("sec.mp4", f, "video/mp4")}, data={
                "start_time": 0.0,
                "duration": 1.0,
                "aspect_ratio": "original",
                "burn_captions": "false"
            })
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication required", res.json()["detail"])

    def test_04_batch_slice_clips_without_auth_rejected_401(self):
        """POST /batch-slice-clips without auth must return 401."""
        with open(self.dummy_video_path, "rb") as f:
            res = self.client.post("/batch-slice-clips", files={"file": ("sec.mp4", f, "video/mp4")}, data={
                "clips_json": "[]",
                "burn_captions": "false"
            })
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication required", res.json()["detail"])

    def test_05_full_captions_without_auth_rejected_401(self):
        """POST /full-captions without auth must return 401."""
        with open(self.dummy_video_path, "rb") as f:
            res = self.client.post("/full-captions", files={"file": ("sec.mp4", f, "video/mp4")})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication required", res.json()["detail"])

    def test_06_burn_full_video_captions_without_auth_rejected_401(self):
        """POST /burn-full-video-captions without auth must return 401."""
        with open(self.dummy_video_path, "rb") as f:
            res = self.client.post("/burn-full-video-captions", files={"file": ("sec.mp4", f, "video/mp4")}, data={
                "words_json": "[]"
            })
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication required", res.json()["detail"])

    def test_07_custom_clip_split_without_auth_rejected_401(self):
        """POST /api/custom-clip/split without auth must return 401."""
        with open(self.dummy_video_path, "rb") as f:
            res = self.client.post("/api/custom-clip/split", files={"file": ("sec.mp4", f, "video/mp4")}, data={
                "clip_duration_seconds": 1.0
            })
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication required", res.json()["detail"])

    def test_08_custom_clip_render_clip_without_auth_rejected_401(self):
        """POST /api/custom-clip/render-clip without auth must return 401."""
        res = self.client.post("/api/custom-clip/render-clip", data={
            "job_id": "test_sec_job",
            "filename": "clip_01.mp4"
        })
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication required", res.json()["detail"])

    def test_09_custom_clip_render_batch_zip_without_auth_rejected_401(self):
        """POST /api/custom-clip/render-batch-zip without auth must return 401."""
        res = self.client.post("/api/custom-clip/render-batch-zip", data={
            "job_id": "test_sec_job",
            "clips_overlays_json": "{}"
        })
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication required", res.json()["detail"])

    def test_10_invalid_or_fake_token_rejected_401(self):
        """Requests with non-existent fake auth_token must return 401."""
        with open(self.dummy_video_path, "rb") as f:
            res = self.client.post("/slice-clip", files={"file": ("sec.mp4", f, "video/mp4")}, data={
                "start_time": 0.0,
                "duration": 1.0,
                "aspect_ratio": "original",
                "burn_captions": "false",
                "auth_token": "fake_hacker_token_12345"
            })
        self.assertEqual(res.status_code, 401)
        self.assertIn("Session expired or invalid login", res.json()["detail"])

    def test_11_valid_auth_token_allowed_and_review_gating_enforced(self):
        """
        Tests the end-to-end security flow:
        1. Valid user registers and receives genuine token.
        2. Endpoint succeeds with valid token (HTTP 200).
        3. When user reaches 5 completed videos without review, generation is blocked (HTTP 403).
        4. Attempting to bypass by omitting token returns 401 (blocked).
        5. Submitting review unlocks generation again (HTTP 200).
        """
        uid_str = uuid.uuid4().hex[:8]
        email = f"sec_user_{uid_str}@example.com"
        reg = self.client.post("/api/auth/signup", json={"email": email, "password": "secure_password_123"}).json()
        token = reg["token"]
        user_id = reg["user"]["id"]

        # 1. Valid user can slice clip successfully
        with open(self.dummy_video_path, "rb") as f:
            res_allowed = self.client.post("/slice-clip", files={"file": ("sec.mp4", f, "video/mp4")}, data={
                "start_time": 0.0,
                "duration": 1.0,
                "aspect_ratio": "original",
                "burn_captions": "false",
                "auth_token": token
            })
        self.assertEqual(res_allowed.status_code, 200)

        # 2. Simulate user completing 5 videos
        for i in range(1, 6):
            auth_db.record_completed_video_for_user(user_id, f"test_vid_{i}.mp4_100_{i}")

        # 3. 6th generation attempt with token -> Blocked by 403 Review Required
        with open(self.dummy_video_path, "rb") as f:
            res_blocked = self.client.post("/slice-clip", files={"file": ("sec.mp4", f, "video/mp4")}, data={
                "start_time": 0.0,
                "duration": 1.0,
                "aspect_ratio": "original",
                "burn_captions": "false",
                "auth_token": token
            })
        self.assertEqual(res_blocked.status_code, 403)
        self.assertIn("Review required", res_blocked.json()["detail"])

        # 4. Attempting to bypass by removing auth_token -> Blocked by 401
        with open(self.dummy_video_path, "rb") as f:
            res_bypass_attempt = self.client.post("/slice-clip", files={"file": ("sec.mp4", f, "video/mp4")}, data={
                "start_time": 0.0,
                "duration": 1.0,
                "aspect_ratio": "original",
                "burn_captions": "false"
            })
        self.assertEqual(res_bypass_attempt.status_code, 401)

        # 5. User submits review -> Unlocks immediately!
        rev_res = self.client.post("/api/submit-review", json={
            "auth_token": token,
            "rating": 5,
            "review_text": "Great security and video clipper!"
        })
        self.assertEqual(rev_res.status_code, 200)

        # 6. Generation is now unlocked!
        with open(self.dummy_video_path, "rb") as f:
            res_unlocked = self.client.post("/slice-clip", files={"file": ("sec.mp4", f, "video/mp4")}, data={
                "start_time": 0.0,
                "duration": 1.0,
                "aspect_ratio": "original",
                "burn_captions": "false",
                "auth_token": token
            })
        self.assertEqual(res_unlocked.status_code, 200)

if __name__ == "__main__":
    unittest.main()
