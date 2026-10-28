import os
import time
import unittest
from fastapi.testclient import TestClient
import main

class TestSecurityVuln3DiskCleanup(unittest.TestCase):
    """
    Automated security verification for Vulnerability #3:
    Disk Space Exhaustion and File Accumulation Prevention.
    """

    def setUp(self):
        self.client = TestClient(main.app)
        self.clips_dir = main.CLIPS_DIR

    def test_01_purge_old_files_preserves_new_files(self):
        """Old files (> 1 hr) are purged, while fresh files are safely kept."""
        old_file = os.path.join(self.clips_dir, "test_stale_clip_999.mp4")
        fresh_file = os.path.join(self.clips_dir, "test_fresh_clip_111.mp4")

        with open(old_file, "w") as f:
            f.write("stale_data")
        with open(fresh_file, "w") as f:
            f.write("fresh_data")

        # Fake old timestamp (2 hours ago)
        two_hours_ago = time.time() - 7200
        os.utime(old_file, (two_hours_ago, two_hours_ago))

        # Run cleanup with 3600s threshold
        purged = main.cleanup_old_generated_clips(max_age_seconds=3600)

        self.assertGreaterEqual(purged, 1)
        self.assertFalse(os.path.exists(old_file), "Old stale file should have been purged")
        self.assertTrue(os.path.exists(fresh_file), "Fresh file should remain intact")

        # Clean up fresh file
        if os.path.exists(fresh_file):
            os.remove(fresh_file)

    def test_02_purge_old_custom_directories(self):
        """Old stale custom clip directories are purged completely."""
        old_dir = os.path.join(self.clips_dir, "custom_test_stale_dir_999")
        os.makedirs(old_dir, exist_ok=True)
        dummy_in_dir = os.path.join(old_dir, "clip_01.mp4")
        with open(dummy_in_dir, "w") as f:
            f.write("data")

        two_hours_ago = time.time() - 7200
        os.utime(old_dir, (two_hours_ago, two_hours_ago))

        purged = main.cleanup_old_generated_clips(max_age_seconds=3600)
        self.assertGreaterEqual(purged, 1)
        self.assertFalse(os.path.exists(old_dir), "Old stale custom dir should have been purged")

    def test_03_download_caption_file_works(self):
        """POST /download-caption-file returns file properly."""
        res = self.client.post("/download-caption-file", data={
            "content": "1\n00:00:00,000 --> 00:00:01,000\nHello Security",
            "file_format": "srt",
            "filename": "sec_test_subtitles"
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn("Hello Security", res.text)

if __name__ == "__main__":
    unittest.main()
