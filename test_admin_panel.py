import os
import unittest
import uuid
import json
from fastapi.testclient import TestClient

import main
import auth_db
import email_service

class TestAdminPanelSecurityAndFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        
        # Unique emails for test runs
        cls.admin_email = f"test_admin_{uuid.uuid4().hex[:6]}@example.com"
        cls.admin_password = "AdminSecretPassword123!"
        os.environ["ADMIN_EMAILS"] = f"{cls.admin_email},ahmadalikhan1009@gmail.com"
        
        cls.regular_email = f"regular_user_{uuid.uuid4().hex[:6]}@example.com"
        cls.regular_password = "RegularUserPassword123!"

        # Ensure regular user is registered and logged in
        auth_db.signup_user(cls.regular_email, cls.regular_password)
        _, _, reg_data = auth_db.login_user(cls.regular_email, cls.regular_password)
        cls.regular_token = reg_data["token"]

        # Ensure test admin user is registered and logged in
        auth_db.signup_user(cls.admin_email, cls.admin_password)
        _, _, adm_data = auth_db.login_user(cls.admin_email, cls.admin_password)
        cls.admin_token = adm_data["token"]

    @classmethod
    def tearDownClass(cls):
        import supabase_db
        import requests
        headers = supabase_db._get_headers()
        sb_url = supabase_db.get_supabase_url()
        for em in [cls.admin_email, cls.regular_email]:
            try:
                requests.delete(f"{sb_url}/rest/v1/users?email=eq.{em}", headers=headers)
                requests.delete(f"{sb_url}/rest/v1/reviews?user_email=eq.{em}", headers=headers)
            except Exception:
                pass

    def test_01_unauthenticated_requests_are_blocked(self):
        """Verify unauthenticated requests cannot access admin endpoints (HTTP 401)."""
        endpoints = [
            "/api/admin/check",
            "/api/admin/users",
            "/api/admin/reviews",
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 401, f"Endpoint {ep} should require authentication")
            self.assertIn("Authentication required", res.json()["detail"])

        # POST without token
        post_res = self.client.post("/api/admin/reviews/1/read", json={"is_read": True})
        self.assertEqual(post_res.status_code, 401)

    def test_02_ordinary_user_is_forbidden(self):
        """Verify ordinary authenticated users are blocked with HTTP 403 Forbidden."""
        headers = {"Authorization": f"Bearer {self.regular_token}"}
        
        # 1. Check endpoint
        check_res = self.client.get("/api/admin/check", headers=headers)
        self.assertEqual(check_res.status_code, 403)
        self.assertIn("Access denied", check_res.json()["detail"])

        # 2. Users endpoint
        users_res = self.client.get("/api/admin/users", headers=headers)
        self.assertEqual(users_res.status_code, 403)

        # 3. Reviews endpoint
        reviews_res = self.client.get("/api/admin/reviews", headers=headers)
        self.assertEqual(reviews_res.status_code, 403)

        # 4. Mark read endpoint
        read_res = self.client.post("/api/admin/reviews/1/read", headers=headers, json={"is_read": True})
        self.assertEqual(read_res.status_code, 403)

    def test_03_authorized_admin_can_access_check_and_users(self):
        """Verify authorized admin can access user list and passwords/tokens are not exposed."""
        headers = {"Authorization": f"Bearer {self.admin_token}"}
        
        # 1. Admin check
        check_res = self.client.get("/api/admin/check", headers=headers)
        self.assertEqual(check_res.status_code, 200)
        self.assertTrue(check_res.json()["is_admin"])
        self.assertEqual(check_res.json()["email"].lower(), self.admin_email.lower())

        # 2. Users list
        users_res = self.client.get("/api/admin/users", headers=headers)
        self.assertEqual(users_res.status_code, 200)
        data = users_res.json()
        self.assertTrue(data["success"])
        self.assertIsInstance(data["users"], list)
        self.assertGreater(data["total"], 0)

        # Verify password_hash, salt, auth_token are NOT returned
        for u in data["users"]:
            self.assertIn("email", u)
            self.assertIn("clips_count", u)
            self.assertNotIn("password_hash", u)
            self.assertNotIn("salt", u)
            self.assertNotIn("auth_token", u)

    def test_04_admin_users_search_filter(self):
        """Verify search query filters users by email."""
        headers = {"Authorization": f"Bearer {self.admin_token}"}
        res = self.client.get(f"/api/admin/users?q={self.regular_email}&include_test=true", headers=headers)
        self.assertEqual(res.status_code, 200)
        users = res.json()["users"]
        self.assertTrue(any(u["email"].lower() == self.regular_email.lower() for u in users))

        # Search for non-existent user
        none_res = self.client.get("/api/admin/users?q=non_existent_xyz_12345", headers=headers)
        self.assertEqual(none_res.status_code, 200)
        self.assertEqual(len(none_res.json()["users"]), 0)

    def test_05_admin_reviews_retrieval_and_read_status(self):
        """Verify admin can view reviews and toggle read/unread status safely."""
        headers = {"Authorization": f"Bearer {self.admin_token}"}

        # Submit a test review first
        rev_text = f"Automated test feedback {uuid.uuid4().hex[:6]}"
        sub_res = self.client.post("/api/submit-review", json={
            "auth_token": self.regular_token,
            "rating": 5,
            "review_text": rev_text
        })
        self.assertEqual(sub_res.status_code, 200)

        # Admin fetches reviews
        rev_res = self.client.get("/api/admin/reviews?include_test=true", headers=headers)
        self.assertEqual(rev_res.status_code, 200)
        reviews = rev_res.json()["reviews"]
        self.assertIsInstance(reviews, list)
        self.assertGreater(len(reviews), 0)

        # Locate our test review
        target_rev = next((r for r in reviews if r.get("review_text") == rev_text), None)
        self.assertIsNotNone(target_rev)
        rev_id = target_rev["id"]

        # Mark as read
        mark_res = self.client.post(f"/api/admin/reviews/{rev_id}/read", headers=headers, json={"is_read": True})
        self.assertEqual(mark_res.status_code, 200)
        self.assertTrue(mark_res.json()["is_read"])

        # Fetch reviews and verify is_read == True
        updated_res = self.client.get("/api/admin/reviews?include_test=true", headers=headers)
        updated_rev = next((r for r in updated_res.json()["reviews"] if r["id"] == rev_id), None)
        self.assertIsNotNone(updated_rev)
        self.assertTrue(updated_rev["is_read"])

        # Mark as unread
        unread_res = self.client.post(f"/api/admin/reviews/{rev_id}/read", headers=headers, json={"is_read": False})
        self.assertEqual(unread_res.status_code, 200)
        self.assertFalse(unread_res.json()["is_read"])

    def test_06_admin_html_served_and_strictly_scoped(self):
        """Verify /admin serves admin.html containing ONLY Users and Reviews sections."""
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn("Admin Panel", html)
        self.assertIn('id="section-users"', html)
        self.assertIn('id="section-reviews"', html)
        # Verify no unrelated sections
        self.assertNotIn("school-management", html.lower())
        self.assertNotIn("billing", html.lower())
        self.assertNotIn("payment", html.lower())

    def test_07_ordinary_auth_and_15_clip_gating_preserved(self):
        """Verify normal auth and 15-clip review gating behavior are completely preserved."""
        new_email = f"gating_{uuid.uuid4().hex[:6]}@example.com"
        s_res = self.client.post("/api/auth/signup", json={"email": new_email, "password": "password123"})
        self.assertEqual(s_res.status_code, 200)
        tok = s_res.json()["token"]
        uid = s_res.json()["user"]["id"]

        try:
            # At 0 clips, no review required
            me_0 = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
            self.assertFalse(me_0["review_required"])
            self.assertFalse(me_0["is_admin"])

            # Increment to 15 clips -> clip generation is not blocked (review_required remains False)
            auth_db.increment_user_clips(uid, 15)
            me_15 = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
            self.assertFalse(me_15["review_required"])
            self.assertEqual(me_15["user"]["clips_count"], 15)
        finally:
            import supabase_db
            import requests
            headers = supabase_db._get_headers()
            sb_url = supabase_db.get_supabase_url()
            try:
                requests.delete(f"{sb_url}/rest/v1/users?id=eq.{uid}", headers=headers)
            except Exception:
                pass

    def test_08_admin_shows_videos_completed_matching_studio_count(self):
        """Verify admin panel displays Videos Completed matching Studio video counter."""
        # 1. Verify admin.html markup
        admin_path = os.path.join(os.path.dirname(__file__), "admin.html")
        with open(admin_path, "r", encoding="utf-8") as f:
            admin_html = f.read()
        self.assertIn("<th>Videos Completed</th>", admin_html)
        self.assertNotIn("<th>Clips Generated</th>", admin_html)
        self.assertIn("Videos</span>", admin_html)

        # 2. Test user with videos recorded
        new_email = f"match_studio_{uuid.uuid4().hex[:6]}@example.com"
        s_res = self.client.post("/api/auth/signup", json={"email": new_email, "password": "password123"})
        self.assertEqual(s_res.status_code, 200)
        tok = s_res.json()["token"]
        uid = s_res.json()["user"]["id"]

        try:
            # Record 3 videos for this user
            for i in range(1, 4):
                self.client.post(
                    "/api/user/record-video-completed",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"video_key": f"studio_vid_{i}.mp4_500_{i}"}
                )

            # Studio video count from /api/auth/me
            studio_me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
            studio_count = studio_me["videos_count"]
            self.assertEqual(studio_count, 3)

            # Admin user count from /api/admin/users
            admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
            admin_res = self.client.get(f"/api/admin/users?q={new_email}&include_test=true", headers=admin_headers).json()
            self.assertTrue(admin_res["success"])
            matched_users = [u for u in admin_res["users"] if u["email"].lower() == new_email.lower()]
            self.assertEqual(len(matched_users), 1)
            admin_user = matched_users[0]

            # Verify admin video count exactly matches Studio video count
            self.assertEqual(admin_user["videos_count"], studio_count)
            self.assertEqual(admin_user["completed_videos_count"], studio_count)
            # Verify clips_count remains preserved
            self.assertIn("clips_count", admin_user)
        finally:
            import supabase_db
            import requests
            headers = supabase_db._get_headers()
            sb_url = supabase_db.get_supabase_url()
            try:
                requests.delete(f"{sb_url}/rest/v1/users?id=eq.{uid}", headers=headers)
            except Exception:
                pass

if __name__ == "__main__":
    unittest.main()
