from video_utils import _find_ffmpeg_exe
import os
import json
import subprocess
import tempfile
import unittest
from fastapi.testclient import TestClient

import main
import video_utils
import custom_clipper

class TestTextOverlayFeature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.test_dir = tempfile.mkdtemp()
        cls.dummy_video_path = os.path.join(cls.test_dir, "test_overlay_input.mp4")

        # Generate a small 3.0 second test video
        cmd = [
            (_find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg"), "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=30",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "libx264", "-c:a", "aac",
            "-t", "3",
            cls.dummy_video_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        import auth_db
        ok, _, u = auth_db.signup_user("overlay_tester@example.com", "pass1234password")
        if not ok:
            ok, _, u = auth_db.login_user("overlay_tester@example.com", "pass1234password")
        cls.auth_token = u["token"]

    @classmethod
    def tearDownClass(cls):
        import shutil
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_generate_ass_without_overlay(self):
        """Verify standard ASS generation without overlay is completely unchanged."""
        ass_path = os.path.join(self.test_dir, "test_no_overlay.ass")
        words = [{"word": "Hello", "start": 0.0, "end": 1.0}]
        video_utils.generate_ass_subtitles(words, ass_path)

        with open(ass_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Style: Default", content)
        self.assertNotIn("Style: OverlayStyle", content)
        self.assertIn("HELLO", content.upper())

    def test_02_generate_ass_with_overlay(self):
        """Verify ASS subtitle generation with custom text overlay parameters."""
        ass_path = os.path.join(self.test_dir, "test_with_overlay.ass")
        words = [{"word": "Testing", "start": 0.0, "end": 1.0}]
        overlay_params = {
            "text": "FOLLOW @MYCHANNEL\nEpisode 1",
            "font_family": "Arial",
            "font_size": 32,
            "text_color": "#ffcc00",
            "align": "center",
            "box_style": "box",
            "bg_color": "#000000",
            "bg_opacity": 70,
            "pos_x_percent": 50,
            "pos_y_percent": 20
        }

        video_utils.generate_ass_subtitles(
            words=words,
            ass_file_path=ass_path,
            overlay_params=overlay_params,
            clip_duration=3.0
        )

        with open(ass_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Style: OverlayStyle", content)
        self.assertIn("Arial", content)
        self.assertIn("FOLLOW @MYCHANNEL\\NEpisode 1", content)
        self.assertIn("\\an5", content) # center alignment
        self.assertIn("\\pos(", content)

    def test_03_generate_ass_overlay_only_no_words(self):
        """Verify ASS subtitle generation when only overlay is requested (no captions)."""
        ass_path = os.path.join(self.test_dir, "test_overlay_only.ass")
        overlay_params = {
            "text": "WATERMARK LOGO",
            "font_family": "Montserrat",
            "font_size": 24,
            "text_color": "#ffffff",
            "align": "right",
            "box_style": "none",
            "pos_x_percent": 85,
            "pos_y_percent": 10
        }

        video_utils.generate_ass_subtitles(
            words=None,
            ass_file_path=ass_path,
            overlay_params=overlay_params,
            clip_duration=2.5
        )

        with open(ass_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Style: OverlayStyle", content)
        self.assertIn("WATERMARK LOGO", content)
        self.assertIn("\\an6", content) # right alignment

    def test_04_trim_video_clip_with_overlay(self):
        """Verify trim_video_clip burns overlay into output video."""
        out_path = os.path.join(self.test_dir, "test_trim_overlay_out.mp4")
        overlay_params = {
            "text": "EPISODE 10",
            "font_family": "Montserrat",
            "font_size": 30,
            "text_color": "#ffffff",
            "align": "center",
            "pos_x_percent": 50,
            "pos_y_percent": 20
        }
        res = video_utils.trim_video_clip(
            input_path=self.dummy_video_path,
            output_path=out_path,
            start_time=0.0,
            duration=2.0,
            aspect_ratio="9:16",
            fit_mode="fit",
            pad_color="black",
            words=None,
            style_options={"overlay": overlay_params},
            burn_captions=False
        )
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 1000)

    def test_05_custom_clipper_with_overlay(self):
        """Verify custom_clipper.slice_custom_clip burns overlay when requested."""
        out_path = os.path.join(self.test_dir, "test_custom_clip_overlay.mp4")
        overlay_params = {
            "text": "CUSTOM CLIP TITLE",
            "font_family": "Montserrat",
            "font_size": 28,
            "text_color": "#ffffff",
            "align": "center",
            "pos_x_percent": 50,
            "pos_y_percent": 15
        }
        ok = custom_clipper.slice_custom_clip(
            input_path=self.dummy_video_path,
            output_path=out_path,
            start_time=0.0,
            duration=2.0,
            overlay_params=overlay_params
        )
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 1000)

    def test_06_endpoint_custom_clip_split_with_overlay(self):
        """Verify /api/custom-clip/split API with overlay_json."""
        overlay_data = {
            "text": "API OVERLAY TEST",
            "font_family": "Montserrat",
            "font_size": 24,
            "text_color": "#ffffff",
            "align": "center",
            "pos_x_percent": 50,
            "pos_y_percent": 20
        }
        with open(self.dummy_video_path, "rb") as f:
            response = self.client.post(
                "/api/custom-clip/split",
                files={"file": ("test.mp4", f, "video/mp4")},
                data={
                    "clip_duration_seconds": 1.5,
                    "overlay_json": json.dumps(overlay_data),
                    "auth_token": self.auth_token
                }
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("total_clips"), 2)

    def test_07_endpoint_slice_clip_with_overlay(self):
        """Verify /slice-clip API endpoint with overlay_json."""
        overlay_data = {
            "text": "SHORTS OVERLAY",
            "font_family": "Montserrat",
            "font_size": 28,
            "text_color": "#ffffff",
            "align": "center",
            "pos_x_percent": 50,
            "pos_y_percent": 15
        }
        with open(self.dummy_video_path, "rb") as f:
            response = self.client.post(
                "/slice-clip",
                files={"file": ("test.mp4", f, "video/mp4")},
                data={
                    "start_time": 0.0,
                    "duration": 1.5,
                    "aspect_ratio": "9:16",
                    "fit_mode": "fit",
                    "pad_color": "black",
                    "words_json": json.dumps([]),
                    "burn_captions": "false",
                    "overlay_json": json.dumps(overlay_data),
                    "auth_token": self.auth_token
                }
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("content-type"), "video/mp4")

if __name__ == "__main__":
    unittest.main()
