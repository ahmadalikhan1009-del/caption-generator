import unittest
from fastapi.testclient import TestClient
import main

class TestSecurityVuln2CORS(unittest.TestCase):
    """
    Automated security verification for Vulnerability #2:
    Prevents Wildcard CORS with Credentials and verifies cross-origin restrictions.
    """

    def setUp(self):
        self.client = TestClient(main.app)

    def test_01_trusted_origin_allowed(self):
        """Trusted local origin receives valid CORS headers."""
        res = self.client.options(
            "/api/auth/me",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "GET"
            }
        )
        self.assertEqual(res.headers.get("access-control-allow-origin"), "http://localhost:8000")
        self.assertEqual(res.headers.get("access-control-allow-credentials"), "true")

    def test_02_malicious_origin_rejected(self):
        """Untrusted external origin (e.g. evil-hacker.com) does NOT receive CORS allow-origin."""
        res = self.client.options(
            "/api/auth/me",
            headers={
                "Origin": "https://evil-hacker.com",
                "Access-Control-Request-Method": "GET"
            }
        )
        # Untrusted origin must NOT be reflected in access-control-allow-origin
        self.assertNotEqual(res.headers.get("access-control-allow-origin"), "https://evil-hacker.com")
        self.assertNotEqual(res.headers.get("access-control-allow-origin"), "*")

    def test_03_no_wildcard_with_credentials(self):
        """Wildcard '*' must never be combined with allow-credentials: true."""
        res = self.client.options(
            "/api/auth/me",
            headers={
                "Origin": "http://127.0.0.1:8000",
                "Access-Control-Request-Method": "GET"
            }
        )
        origin_hdr = res.headers.get("access-control-allow-origin")
        cred_hdr = res.headers.get("access-control-allow-credentials")
        self.assertNotEqual(origin_hdr, "*", "Wildcard origin cannot be used with credentials")
        self.assertEqual(cred_hdr, "true")

if __name__ == "__main__":
    unittest.main()
