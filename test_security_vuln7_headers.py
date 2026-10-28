import unittest
from fastapi.testclient import TestClient
import main

class TestSecurityVuln7Headers(unittest.TestCase):
    """
    Automated security verification for Vulnerability #7:
    Defense-in-depth HTTP security headers (Clickjacking & MIME sniffing protection).
    """

    def setUp(self):
        self.client = TestClient(main.app)

    def test_01_index_has_security_headers(self):
        """GET / must include clickjacking and MIME-sniffing headers."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("x-frame-options"), "DENY")
        self.assertEqual(res.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(res.headers.get("referrer-policy"), "strict-origin-when-cross-origin")

    def test_02_admin_page_has_security_headers(self):
        """GET /admin must include clickjacking protection."""
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("x-frame-options"), "DENY")
        self.assertEqual(res.headers.get("x-content-type-options"), "nosniff")

if __name__ == "__main__":
    unittest.main()
