import unittest

from backend.main import app, dashboard, root


class ApplicationSmokeTests(unittest.TestCase):
    def test_health_route_is_registered(self):
        routes = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, "methods", set())
        }
        self.assertIn(("GET", "/health"), routes)

    def test_root_reports_paper_mode(self):
        self.assertEqual(root()["mode"], "paper")

    def test_dashboard_never_invents_a_paper_account_balance(self):
        result = dashboard()
        self.assertEqual(result["account_status"], "not_configured")
        self.assertEqual(result["bot_status"], "account_not_configured")
        self.assertIsNone(result["balance"])
        self.assertIsNone(result["equity"])
        self.assertEqual(result["data_type"], "not_configured")


if __name__ == "__main__":
    unittest.main()
