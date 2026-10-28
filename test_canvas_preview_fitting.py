from video_utils import _find_ffmpeg_exe
import os
import re
import unittest
import tempfile
import subprocess
from fastapi.testclient import TestClient

import main
import video_utils

class TestCanvasPreviewAndFitting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.test_dir = tempfile.mkdtemp()
        
        # 1. Create a true 9:16 test video (e.g., 270x480, duration 2s)
        cls.video_916_path = os.path.join(cls.test_dir, "portrait_916.mp4")
        cmd_916 = [
            (_find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg"), "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=270x480:d=2",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "libx264", "-c:a", "aac",
            "-t", "2",
            cls.video_916_path
        ]
        subprocess.run(cmd_916, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 2. Create a true 16:9 test video (e.g., 480x270, duration 2s)
        cls.video_169_path = os.path.join(cls.test_dir, "landscape_169.mp4")
        cmd_169 = [
            (_find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg"), "-y",
            "-f", "lavfi", "-i", "color=c=red:s=480x270:d=2",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "libx264", "-c:a", "aac",
            "-t", "2",
            cls.video_169_path
        ]
        subprocess.run(cmd_169, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        import shutil
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_index_html_canvas_ratio_css(self):
        """Verifies that index.html defines accurate 9:16 and 16:9 responsive canvas aspect ratio rules."""
        index_path = os.path.join(os.path.dirname(__file__), "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        # Check .stage-wrapper 9:16 rules
        self.assertIn("aspect-ratio: 9 / 16;", html)
        self.assertIn("max-width: 360px;", html)
        # Check .stage-wrapper.aspect-landscape 16:9 rules
        self.assertIn("aspect-ratio: 16 / 9;", html)
        # Check orientation and dimension indicator hint
        self.assertNotIn("id=\"canvas-ratio-badge\"", html)
        self.assertIn("ratio-hint-text", html)

    def test_02_update_video_framing_logic_in_html(self):
        """Verifies that updateVideoFraming includes aspect-ratio detection and edge-to-edge auto-fitting."""
        index_path = os.path.join(os.path.dirname(__file__), "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("function updateVideoFraming()", html)
        self.assertIn("isRatioMatch", html)
        self.assertIn("videoPlayer.style.objectFit = 'cover';", html)
        self.assertIn("loadedmetadata", html)
        self.assertIn("updateVideoFraming();", html)

    def test_03_trim_916_video_to_916_canvas_dimensions(self):
        """Verifies that trimming a 9:16 input video with 9:16 aspect ratio yields 1080x1920 without distortion."""
        out_path = os.path.join(self.test_dir, "out_916.mp4")
        video_utils.trim_video_clip(
            input_path=self.video_916_path,
            output_path=out_path,
            start_time=0.0,
            duration=1.0,
            aspect_ratio="9:16",
            fit_mode="fit",
            pad_color="black",
            burn_captions=False
        )
        self.assertTrue(os.path.exists(out_path))
        w, h = video_utils.get_video_dimensions(out_path)
        self.assertEqual(w, 1080)
        self.assertEqual(h, 1920)

    def test_04_trim_169_video_to_169_canvas_dimensions(self):
        """Verifies that trimming a 16:9 input video with 16:9 aspect ratio yields 1920x1080."""
        out_path = os.path.join(self.test_dir, "out_169.mp4")
        video_utils.trim_video_clip(
            input_path=self.video_169_path,
            output_path=out_path,
            start_time=0.0,
            duration=1.0,
            aspect_ratio="16:9",
            fit_mode="fit",
            pad_color="black",
            burn_captions=False
        )
        self.assertTrue(os.path.exists(out_path))
        w, h = video_utils.get_video_dimensions(out_path)
        self.assertEqual(w, 1920)
        self.assertEqual(h, 1080)

    def test_05_trim_169_video_to_916_preserves_content_with_padding(self):
        """Verifies that trimming a 16:9 input into 9:16 in 'fit' mode pads to 1080x1920 without cropping."""
        out_path = os.path.join(self.test_dir, "out_169_to_916.mp4")
        video_utils.trim_video_clip(
            input_path=self.video_169_path,
            output_path=out_path,
            start_time=0.0,
            duration=1.0,
            aspect_ratio="9:16",
            fit_mode="fit",
            pad_color="white",
            burn_captions=False
        )
        self.assertTrue(os.path.exists(out_path))
        w, h = video_utils.get_video_dimensions(out_path)
        self.assertEqual(w, 1080)
        self.assertEqual(h, 1920)

if __name__ == "__main__":
    unittest.main()
