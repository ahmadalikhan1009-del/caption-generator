import os
import re
import unittest
from fastapi.testclient import TestClient

import main
import video_utils

class TestTextBoxResizeAndDelete(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.index_path = os.path.join(os.path.dirname(__file__), "index.html")
        with open(cls.index_path, "r", encoding="utf-8") as f:
            cls.html = f.read()

    def test_01_horizontal_resize_handles_markup_present(self):
        """Verifies clear left and right draggable handles are present in both caption-box and custom-overlay-box."""
        # Caption box handles
        self.assertIn('id="caption-handle-left"', self.html)
        self.assertIn('id="caption-handle-right"', self.html)
        # Custom overlay box handles
        self.assertIn('id="overlay-handle-left"', self.html)
        self.assertIn('id="overlay-handle-right"', self.html)

    def test_02_remove_x_controls_markup_present(self):
        """Verifies visible X remove controls are present on both caption preview and custom text overlay."""
        self.assertIn('id="caption-close-btn"', self.html)
        self.assertIn('id="overlay-close-btn"', self.html)
        # Caption preview restore toggle button in sidebar
        self.assertIn('id="btn-toggle-caption-preview"', self.html)
        self.assertIn('id="caption-preview-btn-text"', self.html)

    def test_03_css_box_geometry_separation_and_wrapping(self):
        """Verifies CSS handles, wrapping, and geometry isolation rules."""
        # Side handles CSS
        self.assertIn(".box-side-handle", self.html)
        self.assertIn("cursor: ew-resize;", self.html)
        self.assertIn(".handle-left", self.html)
        self.assertIn(".handle-right", self.html)
        # Close button CSS
        self.assertIn(".box-close-btn", self.html)
        self.assertIn("background: #ef4444;", self.html)
        # Text wrapping and box-sizing
        self.assertIn("word-break: break-word;", self.html)
        self.assertIn("overflow-wrap: break-word;", self.html)

    def test_04_js_geometry_separated_from_typography(self):
        """Verifies resizing handles adjust box width rather than changing font size."""
        # bindBoxResizing function exists
        self.assertIn("function bindBoxResizing(", self.html)
        self.assertIn("boxEl.style.width =", self.html)
        # Old corner handle font scaling logic must NOT be present in resize listener
        self.assertNotIn("fontSizeSlider.value = newSize;", self.html)
        self.assertNotIn("overlaySizeSlider.value = newSize;", self.html)
        # Typography sliders still exist for explicit user adjustment
        self.assertIn("fontSizeSlider.addEventListener('input'", self.html)
        self.assertIn("overlaySizeSlider.addEventListener('input'", self.html)

    def test_05_x_remove_handlers_and_propagation_prevention(self):
        """Verifies X button click handlers stop propagation and manage overlay/preview state cleanly."""
        self.assertIn("captionCloseBtn.addEventListener('click'", self.html)
        self.assertIn("overlayCloseBtn.addEventListener('click'", self.html)
        self.assertIn("isCaptionPreviewHidden = true;", self.html)
        self.assertIn("overlayEnableToggle.checked = false;", self.html)
        # Verify e.stopPropagation is called to prevent canvas drag/click conflicts
        self.assertIn("e.stopPropagation()", self.html)

    def test_06_caption_restore_toggle_functionality(self):
        """Verifies caption preview can be restored cleanly from sidebar."""
        self.assertIn("btnToggleCaptionPreview.addEventListener('click'", self.html)
        self.assertIn("updateCaptionPreviewToggleButton()", self.html)
        self.assertIn("isCaptionPreviewHidden = !isCaptionPreviewHidden;", self.html)

    def test_07_export_compatibility_preserved(self):
        """Verifies backend ASS subtitle and video generation APIs remain intact and functional."""
        words = [{"word": "TESTING", "start": 0.0, "end": 1.0}]
        style = {
            "font_family": "Montserrat",
            "font_size": 32,
            "text_color": "#ffffff",
            "highlight_color": "#facc15"
        }
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as tf:
            temp_ass = tf.name
        try:
            video_utils.generate_ass_subtitles(words, temp_ass, font_family="Montserrat", font_size=32)
            self.assertTrue(os.path.exists(temp_ass))
            with open(temp_ass, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Style: Default", content)
            self.assertIn("Montserrat", content)
        finally:
            if os.path.exists(temp_ass):
                os.remove(temp_ass)

if __name__ == "__main__":
    unittest.main()
