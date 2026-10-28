import unittest
import os
import re
import tempfile
from clipper import reconstruct_sentences_from_words, clean_word_text, HOOK_WORDS
from video_utils import generate_ass_subtitles

class TestIssues123(unittest.TestCase):

    def test_issue_1_urdu_hindi_reconstruction_and_hooks(self):
        """Verify Urdu terminal punctuation (including Arabic/Urdu question mark) and engagement hooks."""
        # Check Urdu hooks
        self.assertIn("kya", HOOK_WORDS)
        self.assertIn("kyun", HOOK_WORDS)
        self.assertIn("raaz", HOOK_WORDS)
        self.assertIn("zindagi", HOOK_WORDS)

        # Test sentence grouping with Urdu question mark '؟'
        words = [
            {"word": "yeh", "start": 0.0, "end": 0.4},
            {"word": "kya", "start": 0.4, "end": 0.8},
            {"word": "hai؟", "start": 0.8, "end": 1.2},
            {"word": "dusra", "start": 1.3, "end": 1.7},
            {"word": "jumla", "start": 1.7, "end": 2.1},
            {"word": "hai۔", "start": 2.1, "end": 2.5}
        ]
        sentences = reconstruct_sentences_from_words(words)
        self.assertEqual(len(sentences), 2)
        self.assertIn("yeh kya hai؟", sentences[0]["text"])
        self.assertIn("dusra jumla hai۔", sentences[1]["text"])

    def test_issue_2_html_resizing_handles_separated(self):
        """Verify that index.html distinguishes cornerHandle (proportional) from side handles (width-only)."""
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()

        # Check that corner handle updates font size and sliders
        self.assertIn("if (currentHandle === 'corner')", html)
        self.assertIn("let newFontSize = Math.round(startFontSize * scaleFactor)", html)
        self.assertIn("fontSizeSlider.value = newFontSize", html)
        
        # Check that right and left handles are isolated and do not change font size
        self.assertIn("else if (currentHandle === 'right')", html)
        self.assertIn("else if (currentHandle === 'left')", html)

    def test_issue_3_ass_subtitles_proportional_scaling_and_margins(self):
        """Verify ASS subtitles proportionally scale font size and apply box width margins."""
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as tf:
            ass_path = tf.name

        try:
            words = [
                {"word": "HELLO", "start": 0.0, "end": 0.5},
                {"word": "WORLD", "start": 0.5, "end": 1.0}
            ]
            # 9:16 portrait: 1080x1920, preview_height=640, font_size=32, box_width_percent=80%
            generate_ass_subtitles(
                words=words,
                ass_file_path=ass_path,
                font_size=32,
                stroke_width=3,
                box_width_percent=80.0,
                pos_y_percent=70.0,
                preview_height=640.0,
                play_res_x=1080,
                play_res_y=1920
            )

            with open(ass_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 32px font scaled by (1920 / 640) = 3x -> 96px
            self.assertIn("Style: Default,Montserrat,96,", content)
            
            # Stroke 3 * 3 = 9
            # Margin: 80% of 1080 = 864px. Margin on each side = (1080 - 864) / 2 = 108px
            self.assertIn(",108,108,", content)

            # Check 16:9 landscape: 1920x1080, preview_height=450, font_size=30, box_width_percent=70%
            generate_ass_subtitles(
                words=words,
                ass_file_path=ass_path,
                font_size=30,
                stroke_width=2,
                box_width_percent=70.0,
                pos_y_percent=75.0,
                preview_height=450.0,
                play_res_x=1920,
                play_res_y=1080
            )

            with open(ass_path, "r", encoding="utf-8") as f:
                content_169 = f.read()

            # 30px font scaled by (1080 / 450) = 2.4x -> 72px
            self.assertIn("Style: Default,Montserrat,72,", content_169)
            
            # Margin: 70% of 1920 = 1344px. Margin on each side = (1920 - 1344) / 2 = 288px
            self.assertIn(",288,288,", content_169)
        finally:
            if os.path.exists(ass_path):
                os.remove(ass_path)

if __name__ == "__main__":
    unittest.main()
