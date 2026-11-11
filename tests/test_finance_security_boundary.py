import unittest

from fastapi.middleware.cors import CORSMiddleware

from backend.main import app


class FinanceSecurityBoundaryTests(unittest.TestCase):
    def test_wildcard_cors_is_not_enabled(self):
        cors_middleware = [
            middleware
            for middleware in app.user_middleware
            if middleware.cls is CORSMiddleware
        ]
        self.assertEqual(cors_middleware, [])

    def test_finance_api_is_documented_as_local_single_user(self):
        from pathlib import Path

        documentation = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "PERSONAL_FINANCE_SECURITY.md"
        ).read_text(encoding="utf-8")
        self.assertIn("local, single-user", documentation)
        self.assertIn("127.0.0.1", documentation)
        self.assertIn("Do not expose this service", documentation)


if __name__ == "__main__":
    unittest.main()
