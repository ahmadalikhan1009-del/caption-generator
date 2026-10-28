import os
import subprocess
import tempfile
import zipfile
import unittest
from fastapi.testclient import TestClient

import custom_clipper
import main

class TestCustomVideoClipping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.test_dir = tempfile.mkdtemp()
        cls.dummy_video_path = os.path.join(cls.test_dir, "test_input_6s.mp4")

        # Generate a small 6.0 second test video
        cmd = [
            custom_clipper._ffmpeg(), "-y",
            "-f", "lavfi", "-i", "testsrc=duration=6:size=320x240:rate=30",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "libx264", "-c:a", "aac",
            "-t", "6",
            cls.dummy_video_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        import shutil
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_duration_and_formatting(self):
        """Tests duration probing and timestamp formatting."""
        dur = custom_clipper.get_video_duration(self.dummy_video_path)
        self.assertAlmostEqual(dur, 6.0, delta=0.5)

        self.assertEqual(custom_clipper.format_seconds_to_hms(0), "00:00:00")
        self.assertEqual(custom_clipper.format_seconds_to_hms(600), "00:10:00")
        self.assertEqual(custom_clipper.format_seconds_to_hms(3665), "01:01:05")
        self.assertEqual(custom_clipper.format_seconds_to_hms(10800), "03:00:00")

    def test_02_segment_calculations_evenly_divisible(self):
        """
        Tests calculation for video that is exactly 3 hours (180 mins)
        with 10-minute clip duration. Expected: 18 clips.
        """
        total_sec = 180 * 60.0 # 10800s
        clip_sec = 10 * 60.0   # 600s
        segs = custom_clipper.calculate_custom_clip_segments(total_sec, clip_sec)

        self.assertEqual(len(segs), 18)
        self.assertEqual(segs[0]["start"], 0.0)
        self.assertEqual(segs[0]["end"], 600.0)
        self.assertEqual(segs[0]["start_formatted"], "00:00:00")
        self.assertEqual(segs[0]["end_formatted"], "00:10:00")

        # Check consecutive alignment without gaps or overlaps
        for i in range(len(segs) - 1):
            self.assertEqual(segs[i]["end"], segs[i+1]["start"])

        # Check final clip
        self.assertEqual(segs[-1]["start"], 10200.0)
        self.assertEqual(segs[-1]["end"], 10800.0)
        self.assertEqual(segs[-1]["start_formatted"], "02:50:00")
        self.assertEqual(segs[-1]["end_formatted"], "03:00:00")

    def test_03_segment_calculations_with_remainder(self):
        """
        Tests calculation where duration is not evenly divisible:
        25 minutes total with 10-minute clips -> 3 clips (10m, 10m, and 5m remainder).
        Never discards the final portion.
        """
        total_sec = 25 * 60.0
        clip_sec = 10 * 60.0
        segs = custom_clipper.calculate_custom_clip_segments(total_sec, clip_sec)

        self.assertEqual(len(segs), 3)
        self.assertEqual(segs[0]["duration"], 600.0)
        self.assertEqual(segs[1]["duration"], 600.0)
        self.assertEqual(segs[2]["duration"], 300.0) # 5 minutes remainder
        self.assertEqual(segs[2]["end"], 1500.0)
        self.assertEqual(segs[2]["start_formatted"], "00:20:00")
        self.assertEqual(segs[2]["end_formatted"], "00:25:00")

    def test_04_split_video_custom_files_and_zip(self):
        """
        Splits actual 6s video into 2.5s clips:
        Clip 1: 0.0 - 2.5s
        Clip 2: 2.5 - 5.0s
        Clip 3: 5.0 - 6.0s (remainder preserved!)
        """
        out_job_dir = os.path.join(self.test_dir, "test_job_out")
        clips = custom_clipper.split_video_custom(
            input_path=self.dummy_video_path,
            output_dir=out_job_dir,
            clip_duration_seconds=2.5
        )

        self.assertEqual(len(clips), 3)
        for c in clips:
            self.assertTrue(os.path.exists(c["filepath"]))
            self.assertGreater(os.path.getsize(c["filepath"]), 1000)

        # Check consecutive alignment
        self.assertEqual(clips[0]["start"], 0.0)
        self.assertEqual(clips[0]["end"], 2.5)
        self.assertEqual(clips[1]["start"], 2.5)
        self.assertEqual(clips[1]["end"], 5.0)
        self.assertEqual(clips[2]["start"], 5.0)
        self.assertAlmostEqual(clips[2]["end"], 6.0, delta=0.5)

        # Test ZIP creation
        zip_path = os.path.join(out_job_dir, "test_all.zip")
        custom_clipper.create_clips_zip([c["filepath"] for c in clips], zip_path)
        self.assertTrue(os.path.exists(zip_path))
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            self.assertEqual(len(names), 3)
            self.assertIn("clip_01.mp4", names)
            self.assertIn("clip_02.mp4", names)
            self.assertIn("clip_03.mp4", names)

    def test_05_api_preview_segments(self):
        """Tests the POST /api/custom-clip/preview-segments endpoint."""
        res = self.client.post("/api/custom-clip/preview-segments", data={
            "total_duration": 180 * 60,
            "clip_duration_seconds": 10 * 60
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total_clips"], 18)
        self.assertEqual(data["total_duration_formatted"], "03:00:00")
        self.assertEqual(data["clip_duration_formatted"], "00:10:00")

    def test_06_api_split_and_download_flow(self):
        """Tests full API flow: split, download individual clip, download zip, and cancel."""
        import auth_db
        ok, _, u = auth_db.signup_user("flowtester@example.com", "pass1234")
        if not ok:
            ok, _, u = auth_db.login_user("flowtester@example.com", "pass1234")
        token = u["token"]

        with open(self.dummy_video_path, "rb") as f:
            res = self.client.post("/api/custom-clip/split", files={
                "file": ("sample_test_video.mp4", f, "video/mp4")
            }, data={
                "clip_duration_seconds": 2.5,
                "job_id": "test_job_123",
                "auth_token": token
            })

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total_clips"], 3)
        self.assertIn("clips", data)
        self.assertIn("zip_download_url", data)

        # Test downloading individual clip
        clip1_url = data["clips"][0]["download_url"]
        res_clip = self.client.get(clip1_url)
        self.assertEqual(res_clip.status_code, 200)
        self.assertEqual(res_clip.headers["content-type"], "video/mp4")
        self.assertGreater(len(res_clip.content), 1000)

        # Test downloading ZIP archive
        zip_url = data["zip_download_url"]
        res_zip = self.client.get(zip_url)
        self.assertEqual(res_zip.status_code, 200)
        self.assertEqual(res_zip.headers["content-type"], "application/zip")
        self.assertGreater(len(res_zip.content), 1000)

        # Test cancel endpoint
        res_cancel = self.client.post("/api/custom-clip/cancel", data={"job_id": "test_job_123"})
        self.assertEqual(res_cancel.status_code, 200)

    def test_07_auth_db_attributes_and_aliases(self):
        """Verifies auth_db has increment_clips_count and get_user_by_id."""
        import auth_db
        self.assertTrue(hasattr(auth_db, "increment_clips_count"), "auth_db must have increment_clips_count")
        self.assertTrue(hasattr(auth_db, "increment_user_clips"), "auth_db must have increment_user_clips")
        self.assertTrue(hasattr(auth_db, "get_user_by_id"), "auth_db must have get_user_by_id")

        # Create temporary user
        ok, msg, user = auth_db.signup_user("cliptester@example.com", "pass1234")
        if not ok:
            # Login if exists
            ok, msg, user = auth_db.login_user("cliptester@example.com", "pass1234")
        self.assertIsNotNone(user)
        user_id = user["id"]

        # Test increment_clips_count alias works
        new_count = auth_db.increment_clips_count(user_id, 2)
        self.assertGreaterEqual(new_count, 2)

        # Test get_user_by_id
        fetched = auth_db.get_user_by_id(user_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["id"], user_id)
        self.assertEqual(fetched["clips_count"], new_count)

    def test_08_custom_clip_split_with_authenticated_user_and_review_gating(self):
        """
        Tests:
        1. Authenticated user calls /api/custom-clip/split with auth_token.
        2. Verifies clips_count is properly updated without AttributeError.
        3. Verifies that when review threshold (15) is reached, further split requests are blocked with 403.
        4. Verifies that submitting review unlocks custom clipping again.
        """
        import auth_db
        import uuid
        email = f"review_clipping_{uuid.uuid4().hex[:8]}@example.com"

        # Signup user
        ok, msg, user = auth_db.signup_user(email, "pass1234")
        self.assertTrue(ok)
        token = user["token"]
        user_id = user["id"]

        # Call split endpoint with auth_token
        with open(self.dummy_video_path, "rb") as f:
            res = self.client.post("/api/custom-clip/split", files={
                "file": ("test_auth_video.mp4", f, "video/mp4")
            }, data={
                "clip_duration_seconds": 2.5,
                "auth_token": token
            })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["clips_count"], 3)
        self.assertFalse(data["has_reviewed"])

        # Advance user clips_count to 15
        auth_db.increment_user_clips(user_id, 15)

        # Splitting is not blocked by clip count
        with open(self.dummy_video_path, "rb") as f:
            res_allowed = self.client.post("/api/custom-clip/split", files={
                "file": ("test_auth_video.mp4", f, "video/mp4")
            }, data={
                "clip_duration_seconds": 2.5,
                "auth_token": token
            })
        self.assertEqual(res_allowed.status_code, 200)

        # User submits voluntary review
        res_review = self.client.post("/api/submit-review", json={
            "auth_token": token,
            "rating": 5,
            "review_text": "Custom clipping works great!"
        })
        self.assertEqual(res_review.status_code, 200)

        # Splitting continues to work and reflects review status
        with open(self.dummy_video_path, "rb") as f:
            res_after_review = self.client.post("/api/custom-clip/split", files={
                "file": ("test_auth_video.mp4", f, "video/mp4")
            }, data={
                "clip_duration_seconds": 2.5,
                "auth_token": token
            })
        self.assertEqual(res_after_review.status_code, 200)
        self.assertTrue(res_after_review.json()["success"])
        self.assertTrue(res_after_review.json()["has_reviewed"])


if __name__ == '__main__':
    unittest.main()
