import unittest

from backend.main import app, root


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


if __name__ == "__main__":
    unittest.main()
