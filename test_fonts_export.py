from video_utils import _find_ffmpeg_exe
import os
import subprocess
import tempfile
import unittest
from video_utils import trim_video_clip, FONTS_DIR

class TestFontRendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dummy_video = "test_dummy_video.mp4"
        cmd = [
            (_find_ffmpeg_exe("ffmpeg.exe") or "ffmpeg"), "-y",
            "-f", "lavfi", "-i", "color=c=black:s=720x1280:d=1",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-c:v", "libx264", "-c:a", "aac",
            "-t", "1",
            cls.dummy_video
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.dummy_video):
            os.remove(cls.dummy_video)

    def test_all_fonts_render_successfully(self):
        self.assertTrue(os.path.isdir(FONTS_DIR), "fonts directory must exist")
        
        fonts_to_test = [
            # Trending & Viral
            'Montserrat',
            'Outfit',
            'Anton',
            'Bebas Neue',
            'Lexend',
            'Unbounded',
            # Ultra Bold & Punchy
            'Archivo Black',
            'Luckiest Guy',
            'Black Han Sans',
            'Russo One',
            'Bungee',
            'Impact',
            'Arial Black',
            # Clean & Modern
            'Plus Jakarta Sans',
            'Poppins',
            'Space Grotesk',
            'Oswald',
            'Rubik',
            # Stylized & Expressive
            'Syne',
            'Righteous',
            'Bangers',
            'Titan One',
            'Playfair Display',
            'Cinzel',
            'Permanent Marker',
            # Multilingual
            'Nirmala UI'
        ]

        self.assertEqual(len(fonts_to_test), 26)

        for font in fonts_to_test:
            with self.subTest(font=font):
                clean_name = font.replace(" ", "_")
                out_video = f"test_out_{clean_name}.mp4"
                caption_opt = {
                    'font_family': font,
                    'font_size': 32,
                    'text_color': '#ffffff',
                    'highlight_color': '#facc15',
                    'stroke_color': '#000000',
                    'stroke_width': 3,
                    'box_style': 'none',
                    'bg_color': '#000000',
                    'bg_opacity': 75,
                    'pos_y_percent': 70,
                    'anim_style': 'hormozi'
                }
                words = [{'word': font.upper(), 'start': 0.1, 'end': 0.9}]
                try:
                    trim_video_clip(
                        input_path=self.dummy_video,
                        output_path=out_video,
                        start_time=0.0,
                        duration=1.0,
                        aspect_ratio='9:16',
                        fit_mode='fill',
                        words=words,
                        style_options=caption_opt
                    )
                    self.assertTrue(os.path.exists(out_video), f"Output video was not created for {font}")
                    self.assertGreater(os.path.getsize(out_video), 1000, f"Output video is too small for {font}")
                finally:
                    if os.path.exists(out_video):
                        os.remove(out_video)

    def test_burn_full_video_captions_trending_font(self):
        from video_utils import burn_full_video_captions
        out_video = "test_full_captions_out.mp4"
        caption_opt = {
            'font_family': 'Outfit',
            'font_size': 32,
            'text_color': '#ffffff',
            'highlight_color': '#facc15',
            'stroke_color': '#000000',
            'stroke_width': 3,
            'box_style': 'none',
            'bg_color': '#000000',
            'bg_opacity': 75,
            'pos_y_percent': 70,
            'anim_style': 'hormozi'
        }
        words = [{'word': 'FULL', 'start': 0.1, 'end': 0.5}, {'word': 'VIDEO', 'start': 0.5, 'end': 0.9}]
        try:
            burn_full_video_captions(
                input_path=self.dummy_video,
                output_path=out_video,
                aspect_ratio='9:16',
                fit_mode='fill',
                words=words,
                style_options=caption_opt
            )
            self.assertTrue(os.path.exists(out_video), "Full video captions export failed")
            self.assertGreater(os.path.getsize(out_video), 1000)
        finally:
            if os.path.exists(out_video):
                os.remove(out_video)

if __name__ == '__main__':
    unittest.main()

