import unittest
import os
import re
from fastapi.testclient import TestClient
from main import app
import auth_db
import supabase_db
import requests

class TestFiveVideoReviewPopup(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.index_path = os.path.join(os.path.dirname(__file__), "index.html")
        with open(self.index_path, "r", encoding="utf-8") as f:
            self.index_html = f.read()
        self.created_test_user_ids = []

    def tearDown(self):
        # Clean up any test users created during test execution
        headers = supabase_db._get_headers()
        sb_url = supabase_db.get_supabase_url()
        for uid in self.created_test_user_ids:
            try:
                requests.delete(f"{sb_url}/rest/v1/users?id=eq.{uid}", headers=headers)
            except Exception:
                pass
            conn = auth_db.get_db_connection()
            try:
                conn.execute("DELETE FROM users WHERE id = ?", (uid,))
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()

    def test_01_index_html_has_5_video_threshold_and_helpers(self):
        """Verifies index.html has the 5-video trigger logic, top-bar display, and storage helpers."""
        self.assertIn("const REVIEW_VIDEO_THRESHOLD = 5;", self.index_html)
        self.assertIn("function recordCompletedVideo(file)", self.index_html)
        self.assertIn("handleVideoCompletion(file", self.index_html)
        self.assertIn("function getCompletedVideos()", self.index_html)
        self.assertIn("function getCompletedVideoStorageKey()", self.index_html)
        self.assertIn("function getReviewDismissedStorageKey()", self.index_html)
        # Top-bar pill must display "Videos: <count>"
        self.assertIn("Videos: ${vidCount}", self.index_html)

    def test_02_old_15_clip_popup_triggers_and_clip_badge_removed(self):
        """Verifies the old 15-clip popup triggers and clips top-bar badge are replaced."""
        self.assertNotIn("if (currentUser.clips_count >= REVIEW_THRESHOLD && !currentUser.has_reviewed)", self.index_html)
        self.assertNotIn("${currentUser.clips_count} Clips", self.index_html)

    def test_03_logic_simulation_4_vs_5_completed_videos(self):
        """
        Simulates the exact completed video counting and popup trigger logic from index.html:
        - 4 completed videos -> No popup
        - 5 completed videos -> Popup appears
        - Retrying the same video -> No duplicate count
        - Incomplete / failed / cancelled -> Not counted
        - Dismissal & submission -> Prevents popup from reappearing
        """
        storage = {}
        current_user = {"id": 9999, "email": "tester@example.com", "has_reviewed": False}

        def get_storage_key():
            uid = current_user["id"] if current_user else "default"
            return f"completed_videos_{uid}"

        def get_dismissed_key():
            uid = current_user["id"] if current_user else "default"
            return f"review_popup_dismissed_{uid}"

        def get_completed_videos():
            raw = storage.get(get_storage_key())
            return list(raw) if raw else []

        def record_completed_video(file_dict):
            if not file_dict:
                return len(get_completed_videos()), False
            fp = f"{file_dict.get('name', 'video')}_{file_dict.get('size', 0)}_{file_dict.get('lastModified', 0)}"
            completed = get_completed_videos()
            is_new = False
            if fp not in completed:
                completed.append(fp)
                is_new = True
                storage[get_storage_key()] = completed
            return len(completed), is_new

        popup_triggered = []

        def handle_video_completion(file_dict):
            count, is_new = record_completed_video(file_dict)
            has_reviewed = current_user and current_user.get("has_reviewed", False)
            if count >= 5 and not has_reviewed:
                popup_triggered.append(count)

        def can_start_new_job():
            if len(get_completed_videos()) >= 5 and not current_user.get("has_reviewed", False):
                return False
            return True

        # 1. Video 1 finishes successfully (even if it produces 20 clips)
        video_1 = {"name": "video_one.mp4", "size": 1024000, "lastModified": 1700000001}
        handle_video_completion(video_1)
        self.assertEqual(len(get_completed_videos()), 1)
        self.assertEqual(len(popup_triggered), 0, "No popup after 1 video")
        self.assertTrue(can_start_new_job())

        # 2. Retrying video 1 -> Must NOT increment count
        handle_video_completion(video_1)
        self.assertEqual(len(get_completed_videos()), 1, "Duplicate retry must not increment count")
        self.assertEqual(len(popup_triggered), 0)

        # 3. Videos 2, 3, 4 finish successfully
        video_2 = {"name": "video_two.mp4", "size": 2048000, "lastModified": 1700000002}
        video_3 = {"name": "video_three.mp4", "size": 3072000, "lastModified": 1700000003}
        video_4 = {"name": "video_four.mp4", "size": 4096000, "lastModified": 1700000004}
        handle_video_completion(video_2)
        handle_video_completion(video_3)
        handle_video_completion(video_4)

        # Test at 4 completed videos: NO POPUP and editing allowed!
        self.assertEqual(len(get_completed_videos()), 4)
        self.assertEqual(len(popup_triggered), 0, "No popup after 4 completed videos")
        self.assertTrue(can_start_new_job(), "User can start jobs when < 5 videos completed")

        # 4. Page reload simulation: storage persists, count remains 4
        self.assertEqual(len(get_completed_videos()), 4, "Page reload preserves completed count without duplicates")

        # 5. Video 5 finishes successfully -> POPUP MUST APPEAR!
        video_5 = {"name": "video_five.mp4", "size": 5120000, "lastModified": 1700000005}
        handle_video_completion(video_5)

        self.assertEqual(len(get_completed_videos()), 5)
        self.assertEqual(len(popup_triggered), 1, "Review popup must appear after 5 completed videos!")
        self.assertEqual(popup_triggered[0], 5)

        # 6. User attempts to start new job before reviewing -> BLOCKED!
        self.assertFalse(can_start_new_job(), "Starting a new job must be blocked after 5 completed videos")

        # 7. User dismisses popup -> STILL BLOCKED from starting new job!
        storage[get_dismissed_key()] = True
        self.assertFalse(can_start_new_job(), "Closing popup must NOT allow starting a new job")

        # 8. User submits review -> UNBLOCKED!
        current_user["has_reviewed"] = True
        self.assertTrue(can_start_new_job(), "Submitting review must unblock continued video editing")

    def test_04_backend_server_side_persistence_and_endpoints(self):
        """Tests server-side tracking of completed videos via API endpoints across logouts/sessions."""
        import uuid
        test_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        reg = self.client.post("/api/auth/signup", json={"email": test_email, "password": "pass1234password"}).json()
        token = reg["token"]
        uid = reg["user"]["id"]
        self.created_test_user_ids.append(uid)

        # Initial state: 0 completed videos
        me_0 = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual(me_0["completed_videos_count"], 0)
        self.assertEqual(me_0["videos_count"], 0)
        self.assertEqual(me_0["user"]["videos_count"], 0)
        self.assertFalse(me_0["review_popup_eligible"])

        # Record 4 unique videos
        for i in range(1, 5):
            res = self.client.post("/api/user/record-video-completed",
                headers={"Authorization": f"Bearer {token}"},
                json={"video_key": f"test_vid_{i}.mp4_100_{i}"}
            ).json()
            self.assertEqual(res["completed_videos_count"], i)
            self.assertEqual(res["videos_count"], i)
            self.assertFalse(res["review_popup_eligible"], f"No popup at {i} videos")

        # Verify retry of video 4 does not duplicate
        retry_res = self.client.post("/api/user/record-video-completed",
            headers={"Authorization": f"Bearer {token}"},
            json={"video_key": "test_vid_4.mp4_100_4"}
        ).json()
        self.assertEqual(retry_res["completed_videos_count"], 4)
        self.assertEqual(retry_res["videos_count"], 4)
        self.assertFalse(retry_res["is_new"])

        # Check /api/auth/me reflects exactly 4 completed videos, NOT eligible yet
        me_4 = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual(me_4["completed_videos_count"], 4)
        self.assertEqual(me_4["videos_count"], 4)
        self.assertEqual(me_4["user"]["videos_count"], 4)
        self.assertFalse(me_4["review_popup_eligible"])

        # Record video 5 -> MUST BECOME ELIGIBLE!
        res_5 = self.client.post("/api/user/record-video-completed",
                headers={"Authorization": f"Bearer {token}"},
            json={"video_key": "test_vid_5.mp4_100_5"}
        ).json()
        self.assertEqual(res_5["completed_videos_count"], 5)
        self.assertEqual(res_5["videos_count"], 5)
        self.assertTrue(res_5["review_popup_eligible"], "Review popup must be eligible at 5 videos!")

        # Simulate logout and re-login on a different browser:
        # Server must reliably return 5 completed videos and review_popup_eligible = True!
        login_resp = self.client.post("/api/auth/login", json={"email": test_email, "password": "pass1234password"}).json()
        self.assertEqual(login_resp["completed_videos_count"], 5)
        self.assertEqual(login_resp["videos_count"], 5)
        self.assertEqual(login_resp["user"]["videos_count"], 5)
        self.assertTrue(login_resp["review_popup_eligible"])

    def test_05_single_video_generating_multiple_clips_increments_video_count_by_one(self):
        """Verifies that 1 video producing 20 clips counts as only 1 video while clips_count tracks clips separately."""
        import uuid
        test_email = f"user_multiclip_{uuid.uuid4().hex[:8]}@example.com"
        reg = self.client.post("/api/auth/signup", json={"email": test_email, "password": "pass1234password"}).json()
        token = reg["token"]
        uid = reg["user"]["id"]
        self.created_test_user_ids.append(uid)

        # Increment clip count by 20 (simulating 20 clips generated from 1 video)
        new_clips = auth_db.increment_user_clips(uid, 20)
        self.assertEqual(new_clips, 20)

        # Record video completed once for this 1 source video
        res = self.client.post("/api/user/record-video-completed",
            headers={"Authorization": f"Bearer {token}"},
            json={"video_key": "long_webinar_20clips_99999"}
        ).json()

        # Video count must be exactly 1, clips count must be 20, and popup must NOT trigger (1 < 5)
        self.assertEqual(res["videos_count"], 1)
        self.assertFalse(res["review_popup_eligible"])

        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual(me["videos_count"], 1)
        self.assertEqual(me["user"]["clips_count"], 20)
        self.assertFalse(me["review_popup_eligible"])

    def test_06_server_side_blocking_at_5_videos(self):
        """Verifies server strictly blocks starting new jobs at 5 videos with HTTP 403, and unblocks upon review."""
        import uuid
        import main
        from fastapi import HTTPException

        test_email = f"user_block_{uuid.uuid4().hex[:8]}@example.com"
        reg = self.client.post("/api/auth/signup", json={"email": test_email, "password": "pass1234password"}).json()
        token = reg["token"]
        uid = reg["user"]["id"]
        self.created_test_user_ids.append(uid)

        # 4 completed videos -> verify_generation_access succeeds
        for i in range(1, 5):
            self.client.post("/api/user/record-video-completed",
                headers={"Authorization": f"Bearer {token}"},
                json={"video_key": f"sample_video_{i}.mp4_200_{i}"}
            )

        user_obj = main.verify_generation_access(token)
        self.assertIsNotNone(user_obj)

        # 5th completed video -> verify_generation_access must raise HTTP 403!
        self.client.post("/api/user/record-video-completed",
            headers={"Authorization": f"Bearer {token}"},
            json={"video_key": "sample_video_5.mp4_200_5"}
        )

        with self.assertRaises(HTTPException) as ctx:
            main.verify_generation_access(token)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Review required", ctx.exception.detail)

        # Submit review -> verify_generation_access succeeds again!
        sub_res = self.client.post("/api/submit-review", json={
            "auth_token": token,
            "rating": 5,
            "review_text": "Great tool for short video editing!"
        })
        self.assertEqual(sub_res.status_code, 200)

        unblocked_user = main.verify_generation_access(token)
        self.assertIsNotNone(unblocked_user)
        self.assertTrue(unblocked_user["has_reviewed"])

if __name__ == "__main__":
    unittest.main()
