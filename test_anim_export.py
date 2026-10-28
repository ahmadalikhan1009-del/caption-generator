from video_utils import _find_ffmpeg_exe
import os
import subprocess
import unittest
from video_utils import trim_video_clip, burn_full_video_captions, generate_ass_subtitles, FONTS_DIR

class TestAnimationStyles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dummy_video = "test_anim_dummy.mp4"
        cmd = [
            (_find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg"), "-y",
            "-f", "lavfi", "-i", "color=c=black:s=720x1280:d=1.5",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "libx264", "-c:a", "aac",
            "-t", "1.5",
            cls.dummy_video
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        cls.sample_words = [
            {"word": "CREATE", "start": 0.1, "end": 0.4},
            {"word": "VIRAL", "start": 0.4, "end": 0.7},
            {"word": "SHORTS", "start": 0.7, "end": 1.0},
            {"word": "TODAY", "start": 1.0, "end": 1.4}
        ]

        cls.all_anim_styles = [
            # 4 original styles
            "hormozi",
            "bounce",
            "karaoke",
            "clean",
            # 8 new styles
            "pop",
            "fade",
            "glow",
            "cinematic",
            "typewriter",
            "single_word",
            "underline",
            "social_box"
        ]

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.dummy_video):
            os.remove(cls.dummy_video)

    def test_ass_generation_all_anim_styles(self):
        """Verifies that generate_ass_subtitles compiles valid ASS dialogue for each style."""
        for anim in self.all_anim_styles:
            with self.subTest(anim_style=anim):
                ass_path = f"test_{anim}.ass"
                try:
                    generate_ass_subtitles(
                        words=self.sample_words,
                        ass_file_path=ass_path,
                        font_family="Montserrat",
                        font_size=32,
                        text_color="#ffffff",
                        highlight_color="#facc15",
                        anim_style=anim
                    )
                    self.assertTrue(os.path.exists(ass_path))
                    with open(ass_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    self.assertIn("[Events]", content)
                    self.assertIn("Dialogue:", content)
                    self.assertGreater(len(content.splitlines()), 10)
                finally:
                    if os.path.exists(ass_path):
                        os.remove(ass_path)

    def test_ffmpeg_video_export_all_anim_styles(self):
        """Verifies that trim_video_clip exports valid MP4 with burned subtitles for each style."""
        for anim in self.all_anim_styles:
            with self.subTest(anim_style=anim):
                out_video = f"test_out_{anim}.mp4"
                caption_opt = {
                    'font_family': 'Montserrat',
                    'font_size': 32,
                    'text_color': '#ffffff',
                    'highlight_color': '#facc15',
                    'stroke_color': '#000000',
                    'stroke_width': 3,
                    'box_style': 'none',
                    'pos_y_percent': 70,
                    'anim_style': anim
                }
                try:
                    trim_video_clip(
                        input_path=self.dummy_video,
                        output_path=out_video,
                        start_time=0.0,
                        duration=1.2,
                        aspect_ratio="9:16",
                        fit_mode="fill",
                        words=self.sample_words,
                        style_options=caption_opt
                    )
                    self.assertTrue(os.path.exists(out_video), f"Failed to export video for anim_style={anim}")
                    self.assertGreater(os.path.getsize(out_video), 1000, f"Exported file too small for {anim}")
                finally:
                    if os.path.exists(out_video):
                        os.remove(out_video)

    def test_full_video_burn_with_new_style(self):
        """Verifies full-video caption burning with a new animation style."""
        out_video = "test_full_burn_pop.mp4"
        caption_opt = {
            'font_family': 'Outfit',
            'font_size': 32,
            'text_color': '#ffffff',
            'highlight_color': '#38bdf8',
            'stroke_color': '#000000',
            'stroke_width': 3,
            'box_style': 'none',
            'pos_y_percent': 70,
            'anim_style': 'pop'
        }
        try:
            burn_full_video_captions(
                input_path=self.dummy_video,
                output_path=out_video,
                aspect_ratio="9:16",
                fit_mode="fill",
                words=self.sample_words,
                style_options=caption_opt
            )
            self.assertTrue(os.path.exists(out_video))
            self.assertGreater(os.path.getsize(out_video), 1000)
        finally:
            if os.path.exists(out_video):
                os.remove(out_video)

if __name__ == '__main__':
    unittest.main()
