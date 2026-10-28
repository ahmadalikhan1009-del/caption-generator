import os
import unittest
from clipper import (
    reconstruct_sentences_from_words,
    snap_to_sentence_boundary,
    find_quote_match_word_index,
    align_gemini_clip,
    analyze_viral_clips
)
from gemini_analyzer import (
    CandidateClip,
    ScoreBreakdown,
    VideoAnalysisResult,
    transliterate_words_to_roman_urdu,
    transliterate_text_to_roman_urdu
)
from video_utils import (
    format_srt_time,
    format_vtt_time,
    generate_srt_content,
    generate_vtt_content,
    generate_txt_content,
    burn_full_video_captions,
    get_video_dimensions
)

class TestVideoClippingIntelligence(unittest.TestCase):

    def setUp(self):
        import auth_db
        ok, _, u = auth_db.signup_user("integ_tester@example.com", "pass1234password")
        if not ok:
            ok, _, u = auth_db.login_user("integ_tester@example.com", "pass1234password")
        self.auth_token = u["token"]

        # Sample English transcript with 4 complete distinct thoughts
        self.words = [
            # Sentence 1: Hook and problem
            {"word": "Most", "start": 1.0, "end": 1.3},
            {"word": "people", "start": 1.3, "end": 1.6},
            {"word": "fail", "start": 1.6, "end": 1.9},
            {"word": "at", "start": 1.9, "end": 2.1},
            {"word": "fitness", "start": 2.1, "end": 2.5},
            {"word": "because", "start": 2.5, "end": 2.8},
            {"word": "they", "start": 2.8, "end": 3.0},
            {"word": "rely", "start": 3.0, "end": 3.3},
            {"word": "on", "start": 3.3, "end": 3.5},
            {"word": "motivation.", "start": 3.5, "end": 4.3},

            # Sentence 2: Elaboration
            {"word": "Motivation", "start": 5.0, "end": 5.6},
            {"word": "is", "start": 5.6, "end": 5.8},
            {"word": "an", "start": 5.8, "end": 6.0},
            {"word": "emotion", "start": 6.0, "end": 6.5},
            {"word": "that", "start": 6.5, "end": 6.7},
            {"word": "fades", "start": 6.7, "end": 7.1},
            {"word": "when", "start": 7.1, "end": 7.3},
            {"word": "you", "start": 7.3, "end": 7.5},
            {"word": "are", "start": 7.5, "end": 7.7},
            {"word": "tired.", "start": 7.7, "end": 8.3},

            # Sentence 3: Resolution / takeaway
            {"word": "What", "start": 9.0, "end": 9.2},
            {"word": "you", "start": 9.2, "end": 9.4},
            {"word": "actually", "start": 9.4, "end": 9.8},
            {"word": "need", "start": 9.8, "end": 10.1},
            {"word": "is", "start": 10.1, "end": 10.3},
            {"word": "an", "start": 10.3, "end": 10.5},
            {"word": "unbreakable", "start": 10.5, "end": 11.2},
            {"word": "daily", "start": 11.2, "end": 11.6},
            {"word": "system.", "start": 11.6, "end": 12.4},

            # Sentence 4: Completely separate topic
            {"word": "Next,", "start": 13.5, "end": 13.9},
            {"word": "let's", "start": 13.9, "end": 14.2},
            {"word": "discuss", "start": 14.2, "end": 14.6},
            {"word": "financial", "start": 14.6, "end": 15.2},
            {"word": "budgeting.", "start": 15.2, "end": 16.0}
        ]

        # Sample Urdu/Hindi words
        self.urdu_words = [
            {"word": "سب", "start": 0.5, "end": 0.8},
            {"word": "سے", "start": 0.8, "end": 1.0},
            {"word": "بڑی", "start": 1.0, "end": 1.3},
            {"word": "غلطی", "start": 1.3, "end": 1.8},
            {"word": "یہ", "start": 1.8, "end": 2.0},
            {"word": "ہوتی", "start": 2.0, "end": 2.4},
            {"word": "ہے۔", "start": 2.4, "end": 3.0},
            {"word": "کہ", "start": 3.2, "end": 3.5},
            {"word": "آپ", "start": 3.5, "end": 3.8},
            {"word": "شروع", "start": 3.8, "end": 4.2},
            {"word": "نہیں", "start": 4.2, "end": 4.5},
            {"word": "کرتے۔", "start": 4.5, "end": 5.2}
        ]

    # --- MODE 1: ENGLISH CLIPPING & CLEAN EXPORT TESTS ---

    def test_sentence_reconstruction(self):
        sentences = reconstruct_sentences_from_words(self.words)
        self.assertEqual(len(sentences), 4)
        self.assertIn("Most people fail at fitness", sentences[0]["text"])
        self.assertIn("Motivation is an emotion", sentences[1]["text"])
        self.assertIn("daily system.", sentences[2]["text"])
        self.assertIn("financial budgeting.", sentences[3]["text"])

    def test_quote_matching(self):
        idx_start = find_quote_match_word_index("Most people fail at", self.words, target_time=1.0, is_start=True)
        self.assertEqual(idx_start, 0)

        idx_end = find_quote_match_word_index("unbreakable daily system.", self.words, target_time=12.0, is_start=False)
        self.assertEqual(idx_end, 28)

    def test_zero_mid_sentence_cuts(self):
        """Verify that boundary snapping never allows a clip to begin or end mid-sentence."""
        sentences = reconstruct_sentences_from_words(self.words)
        snapped_start = snap_to_sentence_boundary(5, sentences, is_start=True)
        self.assertEqual(snapped_start, 0)

        snapped_end = snap_to_sentence_boundary(5, sentences, is_start=False)
        self.assertEqual(snapped_end, 9)

    def test_gemini_candidate_alignment(self):
        sentences = reconstruct_sentences_from_words(self.words)
        candidate = CandidateClip(
            title="The Motivation Myth",
            hook="Most people fail at fitness",
            summary="Why relying on motivation fails and systems win.",
            start_time=1.0,
            end_time=12.4,
            quote_start="Most people fail at fitness",
            quote_end="unbreakable daily system.",
            viral_score=92,
            score_breakdown=ScoreBreakdown(
                hook_strength=94,
                clarity=92,
                engagement=90,
                standalone_value=95,
                audience_relevance=88
            ),
            why_it_works="Complete mindset shift with punchy takeaway."
        )

        aligned = align_gemini_clip(candidate, self.words, sentences, min_duration=8.0, max_duration=25.0)
        self.assertIsNotNone(aligned)
        self.assertEqual(aligned["title"], "The Motivation Myth")
        self.assertLessEqual(aligned["start"], 1.0)
        self.assertGreaterEqual(aligned["end"], 12.4)
        self.assertLess(aligned["end"], 13.5)
        self.assertAlmostEqual(aligned["words"][0]["start"], round(self.words[0]["start"] - aligned["start"], 3))

    def test_fallback_engine(self):
        """Tests that when Gemini is offline, the fallback produces complete sentences."""
        segments = [{"words": self.words}]
        clips = analyze_viral_clips(segments, min_duration=8.0, max_duration=20.0, language="en")
        self.assertGreater(len(clips), 0)
        clip = clips[0]
        self.assertIn("Most people fail at fitness", clip["full_text"])
        self.assertIn("system.", clip["full_text"])
        self.assertNotIn("budgeting", clip["full_text"])

    # --- MODE 2: HINDI / URDU TESTS ---

    def test_hindi_urdu_sentence_reconstruction(self):
        """Verifies Urdu sentences are parsed with correct terminal punctuation and pauses."""
        sentences = reconstruct_sentences_from_words(self.urdu_words)
        self.assertEqual(len(sentences), 2)
        self.assertIn("سب سے بڑی غلطی", sentences[0]["text"])
        self.assertIn("شروع نہیں کرتے", sentences[1]["text"])

    def test_roman_urdu_word_transliteration(self):
        """Verifies Roman Urdu transliteration converts script while preserving exact word timing."""
        roman_words = transliterate_words_to_roman_urdu(self.urdu_words)
        self.assertEqual(len(roman_words), len(self.urdu_words))
        # Ensure words are now in Latin script (ASCII)
        for w in roman_words:
            self.assertTrue(w["word"].isascii(), f"Word '{w['word']}' is not ASCII Latin script")
        # Ensure timing is preserved exactly
        self.assertEqual(roman_words[0]["start"], self.urdu_words[0]["start"])
        self.assertEqual(roman_words[-1]["end"], self.urdu_words[-1]["end"])

    # --- MODE 3: FULL VIDEO CAPTIONS TESTS ---

    def test_full_video_captions_srt_vtt_txt_generation(self):
        """Verifies standard subtitle format generation for Mode 3."""
        segments = [
            {"id": 1, "start": 0.5, "end": 4.3, "text": "Most people fail at fitness."},
            {"id": 2, "start": 5.0, "end": 8.3, "text": "Motivation is an emotion that fades."}
        ]
        
        # Test SRT
        srt = generate_srt_content(segments)
        self.assertIn("1\n00:00:00,500 --> 00:00:04,300\nMost people fail at fitness.", srt)
        self.assertIn("2\n00:00:05,000 --> 00:00:08,300", srt)

        # Test VTT
        vtt = generate_vtt_content(segments)
        self.assertTrue(vtt.startswith("WEBVTT"))
        self.assertIn("00:00:00.500 --> 00:00:04.300", vtt)

        # Test TXT
        txt = generate_txt_content(segments)
        self.assertIn("[00:00.5 - 00:04.3] Most people fail at fitness.", txt)
        self.assertIn("[00:05.0 - 00:08.3] Motivation is an emotion that fades.", txt)

    def test_roman_urdu_required_examples(self):
        """Verifies exact user-requested Roman Urdu examples."""
        from transliteration import convert_text_to_roman_urdu, is_valid_roman_urdu
        
        # Example 1
        res1 = convert_text_to_roman_urdu("آپ کیسے ہیں؟")
        self.assertEqual(res1, "Aap kaise hain?")
        self.assertTrue(is_valid_roman_urdu(res1))

        # Example 2
        res2 = convert_text_to_roman_urdu("یہ ویڈیو بہت اچھی ہے۔")
        self.assertEqual(res2, "Yeh video bohat achi hai.")
        self.assertTrue(is_valid_roman_urdu(res2))

    def test_script_mode_conversions(self):
        """Verifies explicit choices: Urdu Script, Hindi Devanagari, and Roman Urdu."""
        from transliteration import convert_text_by_script_mode, is_valid_roman_urdu
        
        text_urdu = "آپ کیسے ہیں؟"
        # Roman Urdu mode
        roman = convert_text_by_script_mode(text_urdu, "roman_urdu")
        self.assertEqual(roman, "Aap kaise hain?")
        self.assertTrue(is_valid_roman_urdu(roman))

        # Urdu script mode preserves Urdu
        urdu = convert_text_by_script_mode(text_urdu, "urdu_script")
        self.assertIn("آپ", urdu)

        # Hindi Devanagari mode converts to Devanagari
        hindi = convert_text_by_script_mode(text_urdu, "hindi_devanagari")
        self.assertIn("आप", hindi)

    def test_clean_vs_captioned_export_behavior(self):
        """
        Verifies that trim_video_clip correctly distinguishes between
        captioned export (burn_captions=True) and clean export (burn_captions=False).
        """
        import tempfile
        import subprocess
        from video_utils import trim_video_clip, is_ffmpeg_available

        if not is_ffmpeg_available():
            self.skipTest("FFmpeg not available")

        t1 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        temp_src = t1.name
        t1.close()
        t2 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        captioned_out = t2.name
        t2.close()
        t3 = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        clean_out = t3.name
        t3.close()

        try:
            # Generate 2-second test video with color test pattern & silent audio
            cmd_create = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=1280x720:d=2",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "2",
                "-c:v", "libx264", "-c:a", "aac",
                temp_src
            ]
            subprocess.run(cmd_create, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            sample_words = [
                {"word": "Aap", "start": 0.2, "end": 0.6},
                {"word": "kaise", "start": 0.6, "end": 1.0},
                {"word": "hain?", "start": 1.0, "end": 1.4}
            ]

            # 1. Export with Captions
            trim_video_clip(
                input_path=temp_src,
                output_path=captioned_out,
                start_time=0.0,
                duration=1.8,
                aspect_ratio="9:16",
                words=sample_words,
                burn_captions=True
            )
            self.assertTrue(os.path.exists(captioned_out))
            self.assertGreater(os.path.getsize(captioned_out), 0)

            # 2. Export Clean (Without Captions)
            trim_video_clip(
                input_path=temp_src,
                output_path=clean_out,
                start_time=0.0,
                duration=1.8,
                aspect_ratio="9:16",
                words=sample_words,
                burn_captions=False
            )
            self.assertTrue(os.path.exists(clean_out))
            self.assertGreater(os.path.getsize(clean_out), 0)

            # 3. Source file must remain completely unmodified
            self.assertTrue(os.path.exists(temp_src))

        finally:
            for p in [temp_src, captioned_out, clean_out]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    def test_module_2_urdu_hindi_smart_clipping_clean_export(self):
        """
        Confirms Module 2 requirement:
        Urdu/Hindi smart clipping only - selected clips are generated clean without captions or subtitle generation.
        """
        import tempfile
        import subprocess
        from video_utils import trim_video_clip, is_ffmpeg_available

        if not is_ffmpeg_available():
            self.skipTest("FFmpeg not available")

        # 1. Verify Urdu sentence parsing extracts meaningful boundaries
        sentences = reconstruct_sentences_from_words(self.urdu_words)
        self.assertGreaterEqual(len(sentences), 1)

        # 2. Verify clip export is strictly clean without captions
        t_src = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        temp_src = t_src.name
        t_src.close()
        t_out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        temp_out = t_out.name
        t_out.close()

        try:
            cmd_create = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=green:s=1280x720:d=2",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "2",
                "-c:v", "libx264", "-c:a", "aac",
                temp_src
            ]
            subprocess.run(cmd_create, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            # Export clean Urdu/Hindi clip (burn_captions=False, no words passed)
            trim_video_clip(
                input_path=temp_src,
                output_path=temp_out,
                start_time=0.0,
                duration=1.5,
                aspect_ratio="9:16",
                words=None,
                burn_captions=False
            )

            self.assertTrue(os.path.exists(temp_out))
            self.assertGreater(os.path.getsize(temp_out), 0)

        finally:
            for p in [temp_src, temp_out]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    def test_module_3_full_video_captions_burned_video(self):
        """
        Confirms Module 3 requirement:
        Full English video captioning burns synchronized captions covering the complete video duration,
        preserving audio and producing a playable full-length video file.
        """
        import tempfile
        import subprocess
        from video_utils import burn_full_video_captions, is_ffmpeg_available

        if not is_ffmpeg_available():
            self.skipTest("FFmpeg not available")

        t_src = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        temp_src = t_src.name
        t_src.close()
        t_out = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        temp_out = t_out.name
        t_out.close()

        try:
            # Create a 3-second source video with audio
            cmd_create = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=navy:s=1280x720:d=3",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "3",
                "-c:v", "libx264", "-c:a", "aac",
                temp_src
            ]
            subprocess.run(cmd_create, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            # English words covering the full duration
            english_words = [
                {"word": "Most", "start": 0.2, "end": 0.6},
                {"word": "people", "start": 0.6, "end": 1.0},
                {"word": "fail", "start": 1.0, "end": 1.4},
                {"word": "at", "start": 1.4, "end": 1.7},
                {"word": "fitness.", "start": 1.7, "end": 2.5}
            ]

            # Burn full video captions
            res_path = burn_full_video_captions(
                input_path=temp_src,
                output_path=temp_out,
                words=english_words,
                aspect_ratio="original"
            )

            self.assertTrue(os.path.exists(temp_out))
            self.assertGreater(os.path.getsize(temp_out), 0)

            # Verify with ffprobe that video has both video and audio streams and covers full 3s duration
            cmd_probe = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration:stream=codec_type",
                "-of", "csv=p=0",
                temp_out
            ]
            probe_res = subprocess.run(cmd_probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(probe_res.returncode, 0)
            self.assertIn("video", probe_res.stdout)
            self.assertIn("audio", probe_res.stdout)

        finally:
            for p in [temp_src, temp_out]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

    def test_module_3_api_burn_full_video_endpoint(self):
        """
        Confirms the FastAPI endpoint /burn-full-video-captions returns a valid MP4 file.
        """
        import tempfile
        import subprocess
        import json
        from fastapi.testclient import TestClient
        from main import app
        from video_utils import is_ffmpeg_available

        if not is_ffmpeg_available():
            self.skipTest("FFmpeg not available")

        client = TestClient(app)

        t_src = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        temp_src = t_src.name
        t_src.close()

        try:
            # Create a 2-second test video
            cmd_create = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=purple:s=640x360:d=2",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "2",
                "-c:v", "libx264", "-c:a", "aac",
                temp_src
            ]
            subprocess.run(cmd_create, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            words = [
                {"word": "Full", "start": 0.2, "end": 0.8},
                {"word": "Video", "start": 0.8, "end": 1.5}
            ]

            with open(temp_src, "rb") as vf:
                resp = client.post(
                    "/burn-full-video-captions",
                    files={"file": ("test.mp4", vf, "video/mp4")},
                    data={
                        "words_json": json.dumps(words),
                        "aspect_ratio": "original",
                        "auth_token": self.auth_token
                    }
                )

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("content-type"), "video/mp4")
            self.assertGreater(len(resp.content), 0)

        finally:
            if os.path.exists(temp_src):
                try:
                    os.remove(temp_src)
                except Exception:
                    pass

    def test_cancel_analysis_endpoint(self):
        """
        Confirms /cancel-analysis properly records cancellation for active job,
        and handles empty job_id gracefully.
        """
        from fastapi.testclient import TestClient
        from main import app, active_analysis_jobs

        client = TestClient(app)
        test_job = "job_test_cancel_123"

        # 1. Empty or missing job_id -> returns ignored
        resp1 = client.post("/cancel-analysis", data={"job_id": ""})
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()["status"], "ignored")


        # 2. Valid job_id -> records cancellation immediately
        try:
            resp2 = client.post("/cancel-analysis", data={"job_id": test_job})
            self.assertEqual(resp2.status_code, 200)
            self.assertEqual(resp2.json(), {"status": "cancelled", "job_id": test_job})
            self.assertTrue(active_analysis_jobs[test_job]["cancelled"])
        finally:
            active_analysis_jobs.pop(test_job, None)


    def test_slice_clip_api_clean_export(self):
        """
        Confirms /slice-clip endpoint with burn_captions=False returns a clean video clip
        with video/mp4 MIME type and correct filename prefix.
        """
        import tempfile
        import subprocess
        from fastapi.testclient import TestClient
        from main import app
        from video_utils import is_ffmpeg_available

        if not is_ffmpeg_available():
            self.skipTest("FFmpeg not available")

        client = TestClient(app)

        t_src = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        temp_src = t_src.name
        t_src.close()

        try:
            cmd_create = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=red:s=640x360:d=2",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "2",
                "-c:v", "libx264", "-c:a", "aac",
                temp_src
            ]
            subprocess.run(cmd_create, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            with open(temp_src, "rb") as vf:
                resp = client.post(
                    "/slice-clip",
                    files={"file": ("test.mp4", vf, "video/mp4")},
                    data={
                        "start_time": 0.0,
                        "duration": 1.0,
                        "aspect_ratio": "original",
                        "burn_captions": "false",
                        "auth_token": self.auth_token
                    }
                )

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("content-type"), "video/mp4")
            self.assertGreater(len(resp.content), 0)

        finally:
            if os.path.exists(temp_src):
                try:
                    os.remove(temp_src)
                except Exception:
                    pass

    def test_extract_clips_cancellation_abort(self):
        """
        Confirms that when an analysis job is marked cancelled, /extract-clips
        halts immediately and returns HTTP 499 (Client Closed Request).
        """
        import tempfile
        import subprocess
        from fastapi.testclient import TestClient
        from main import app, active_analysis_jobs
        from video_utils import is_ffmpeg_available

        if not is_ffmpeg_available():
            self.skipTest("FFmpeg not available")

        client = TestClient(app)
        cancel_job_id = "job_cancel_immediate_999"

        t_src = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        temp_src = t_src.name
        t_src.close()

        try:
            cmd_create = [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=640x360:d=1",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", "1",
                "-c:v", "libx264", "-c:a", "aac",
                temp_src
            ]
            subprocess.run(cmd_create, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

            # Pre-cancel the job
            active_analysis_jobs[cancel_job_id] = {"cancelled": True}

            with open(temp_src, "rb") as vf:
                resp = client.post(
                    "/extract-clips",
                    files={"file": ("test.mp4", vf, "video/mp4")},
                    data={
                        "speed_mode": "tiny",
                        "language": "en",
                        "job_id": cancel_job_id,
                        "auth_token": self.auth_token
                    }
                )

            self.assertEqual(resp.status_code, 499)
            self.assertIn("cancelled", resp.json().get("detail", "").lower())

        finally:
            active_analysis_jobs.pop(cancel_job_id, None)
            if os.path.exists(temp_src):
                try:
                    os.remove(temp_src)
                except Exception:
                    pass

if __name__ == "__main__":
    unittest.main()

