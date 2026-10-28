import os
import unittest
import tempfile
import subprocess
import uuid
from fastapi.testclient import TestClient
import main
import auth_db

class TestSecurityVuln5IDOR(unittest.TestCase):
    """
    Automated security verification for Vulnerability #5:
    Insecure Direct Object Reference (IDOR) & Unauthorized Video Downloads.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.test_dir = tempfile.mkdtemp()
        cls.dummy_video_path = os.path.join(cls.test_dir, "idor_test.mp4")

        from video_utils import _find_ffmpeg_exe
        ffmpeg_bin = _find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg"
        cmd = [
            ffmpeg_bin, "-y",
            "-f", "lavfi", "-i", "color=c=black:s=160x120:d=2",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "2",
            "-c:v", "libx264", "-c:a", "aac",
            cls.dummy_video_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        import shutil
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_user_cannot_download_another_users_clip_idor_blocked(self):
        """User B cannot access or download clips created by User A (HTTP 403)."""
        # 1. User A signs up and splits video
        email_a = f"usera_{uuid.uuid4().hex[:8]}@example.com"
        reg_a = self.client.post("/api/auth/signup", json={"email": email_a, "password": "passwordA123"}).json()
        token_a = reg_a["token"]

        with open(self.dummy_video_path, "rb") as f:
            res_split = self.client.post("/api/custom-clip/split", files={
                "file": ("user_a_video.mp4", f, "video/mp4")
            }, data={
                "clip_duration_seconds": 1.0,
                "auth_token": token_a
            })

        self.assertEqual(res_split.status_code, 200)
        split_data = res_split.json()
        job_id = split_data["job_id"]
        clip_fn = split_data["clips"][0]["filename"]

        # 2. User A downloads their own clip -> 200 OK
        res_a_dl = self.client.get(f"/api/custom-clip/download/{job_id}/{clip_fn}?token={token_a}")
        self.assertEqual(res_a_dl.status_code, 200)

        # 3. User B signs up
        email_b = f"userb_{uuid.uuid4().hex[:8]}@example.com"
        reg_b = self.client.post("/api/auth/signup", json={"email": email_b, "password": "passwordB123"}).json()
        token_b = reg_b["token"]

        # 4. User B tries to download User A's clip using User A's job_id -> 403 Forbidden!
        res_b_dl = self.client.get(f"/api/custom-clip/download/{job_id}/{clip_fn}?token={token_b}")
        self.assertEqual(res_b_dl.status_code, 403)
        self.assertIn("Access denied", res_b_dl.json()["detail"])

        # 5. User B tries to download User A's ZIP archive -> 403 Forbidden!
        res_b_zip = self.client.get(f"/api/custom-clip/download-zip/{job_id}?token={token_b}")
        self.assertEqual(res_b_zip.status_code, 403)
        self.assertIn("Access denied", res_b_zip.json()["detail"])

        # 6. Unauthenticated attacker tries to download without token -> 401 Unauthorized!
        res_anon_dl = self.client.get(f"/api/custom-clip/download/{job_id}/{clip_fn}")
        self.assertEqual(res_anon_dl.status_code, 401)

if __name__ == "__main__":
    unittest.main()
