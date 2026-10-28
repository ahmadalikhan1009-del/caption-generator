import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import main
import auth_db
import supabase_db


EMPTY_SB_ENV = {
    "SUPABASE_URL": "",
    "SUPABASE_KEY": "",
    "SUPABASE_SECRET_KEY": "",
    "SUPABASE_SERVICE_ROLE_KEY": "",
    "SUPABASE_PUBLISHABLE_KEY": ""
}


class TestSupabaseIntegration(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)

    def tearDown(self):
        supabase_db._supabase_verified = None
        supabase_db._last_check_time = 0.0

    def test_01_db_status_endpoint_default_sqlite(self):
        """When SUPABASE env is empty, active database is SQLite."""
        with patch.dict("os.environ", EMPTY_SB_ENV):
            res = self.client.get("/api/auth/db-status")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["active_database"], "sqlite")
            self.assertFalse(data["supabase_configured"])
            self.assertIn("SQLite", data["detail"])

    def test_02_is_configured_logic(self):
        """Tests that is_configured detects valid vs placeholder credentials."""
        with patch.dict("os.environ", EMPTY_SB_ENV):
            self.assertFalse(supabase_db.is_configured())

        with patch.dict("os.environ", {
            **EMPTY_SB_ENV,
            "SUPABASE_URL": "https://your-project.supabase.co",
            "SUPABASE_KEY": "your_supabase_key"
        }):
            self.assertFalse(supabase_db.is_configured())

        with patch.dict("os.environ", {
            **EMPTY_SB_ENV,
            "SUPABASE_URL": "https://xyzcompany.supabase.co",
            "SUPABASE_KEY": "sb_publishable_123456"
        }):
            self.assertTrue(supabase_db.is_configured())

    @patch("requests.get")
    @patch("requests.post")
    @patch("requests.patch")
    def test_03_mocked_supabase_full_flow(self, mock_patch, mock_post, mock_get):
        """Simulates full Supabase auth, clip counting, and review flow with mocked responses."""
        with patch.dict("os.environ", {
            **EMPTY_SB_ENV,
            "SUPABASE_URL": "https://testproj.supabase.co",
            "SUPABASE_KEY": "dummy_secret_key"
        }):
            # Set default 200 OK for GET requests (test_connection & check_user)
            mock_check_resp = MagicMock()
            mock_check_resp.status_code = 200
            mock_check_resp.json.return_value = []
            mock_get.return_value = mock_check_resp

            self.assertTrue(supabase_db.is_configured())
            self.assertTrue(supabase_db.is_ready(force_check=True))
            self.assertEqual(auth_db.get_db_type(), "supabase")

            # 1. Signup flow

            # POST insert user -> return inserted row
            mock_insert_resp = MagicMock()
            mock_insert_resp.status_code = 201
            mock_insert_resp.json.return_value = [{
                "id": 101,
                "email": "clouduser@example.com",
                "clips_count": 0,
                "has_reviewed": False,
                "auth_token": "token_abc_123"
            }]
            mock_post.return_value = mock_insert_resp

            ok, msg, user_data = auth_db.signup_user("clouduser@example.com", "mypassword123")
            self.assertTrue(ok)
            self.assertEqual(user_data["id"], 101)
            self.assertEqual(user_data["email"], "clouduser@example.com")
            self.assertEqual(user_data["clips_count"], 0)

            # 2. Get user by token
            mock_token_resp = MagicMock()
            mock_token_resp.status_code = 200
            mock_token_resp.json.return_value = [{
                "id": 101,
                "email": "clouduser@example.com",
                "clips_count": 3,
                "has_reviewed": False,
                "auth_token": "token_abc_123"
            }]
            mock_get.return_value = mock_token_resp

            user = auth_db.get_user_by_token("token_abc_123")
            self.assertIsNotNone(user)
            self.assertEqual(user["id"], 101)
            self.assertEqual(user["clips_count"], 3)

            # 3. Increment user clips
            # get_user_by_id returns user with clips_count=3
            mock_patch_resp = MagicMock()
            mock_patch_resp.status_code = 200
            mock_patch.return_value = mock_patch_resp

            new_count = auth_db.increment_user_clips(101, 2)
            self.assertEqual(new_count, 5)

            # 4. Save review
            mock_rev_post = MagicMock()
            mock_rev_post.status_code = 201
            mock_rev_post.json.return_value = [{"id": 501}]
            mock_post.return_value = mock_rev_post

            rev = auth_db.save_user_review(
                user_id=101,
                user_email="clouduser@example.com",
                rating=5,
                review_text="Awesome Supabase integration!",
                owner_email="owner@example.com"
            )
            self.assertIsNotNone(rev)
            self.assertEqual(rev["user_id"], 101)

            # Reset env
            supabase_db.SUPABASE_URL = ""
            supabase_db.SUPABASE_KEY = ""


if __name__ == '__main__':
    unittest.main()
