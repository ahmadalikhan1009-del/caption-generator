import unittest
import uuid
import os
from fastapi.testclient import TestClient
import main
import auth_db

class TestSecurityVuln6PasswordAndXSS(unittest.TestCase):
    """
    Automated security verification for:
    - Vulnerability #6: Weak Password Policy
    - Vulnerability #8: Stored XSS via Email / Registration Sanitization
    """

    def setUp(self):
        self.client = TestClient(main.app)

    def test_01_short_password_rejected(self):
        """Passwords under 8 characters must be rejected."""
        email = f"pwd_test_{uuid.uuid4().hex[:8]}@example.com"
        # Test 4 chars
        res_4 = self.client.post("/api/auth/signup", json={"email": email, "password": "pass"})
        self.assertEqual(res_4.status_code, 400)
        self.assertIn("at least 8 characters", res_4.json()["detail"])

        # Test 7 chars
        res_7 = self.client.post("/api/auth/signup", json={"email": email, "password": "1234567"})
        self.assertEqual(res_7.status_code, 400)
        self.assertIn("at least 8 characters", res_7.json()["detail"])

    def test_02_strong_password_accepted(self):
        """Passwords with 8+ characters are accepted."""
        email = f"pwd_good_{uuid.uuid4().hex[:8]}@example.com"
        res = self.client.post("/api/auth/signup", json={"email": email, "password": "Password123!"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

    def test_03_xss_injection_email_rejected_by_backend(self):
        """Emails containing HTML injection or tags must be rejected."""
        xss_emails = [
            "<script>alert(1)</script>@test.com",
            "<img/src/onerror=alert(1)>@test.com",
            "user'name@test.com",
            'user"name@test.com'
        ]
        for bad_email in xss_emails:
            res = self.client.post("/api/auth/signup", json={"email": bad_email, "password": "ValidPassword123!"})
            self.assertEqual(res.status_code, 400, f"Expected 400 for {bad_email}")
            self.assertIn("valid email address", res.json()["detail"])

    def test_04_index_html_renders_email_safely(self):
        """Verifies that index.html uses textContent for email to prevent XSS."""
        index_path = os.path.join(os.path.dirname(__file__), "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn("emailSpan.textContent = currentUser.email", html)
        self.assertNotIn("emailChip.innerHTML = `<span>${currentUser.email}</span>`", html)

if __name__ == "__main__":
    unittest.main()
