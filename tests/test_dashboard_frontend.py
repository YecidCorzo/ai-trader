"""Static regression tests for the read-only dashboard integration."""

from pathlib import Path
import re
import unittest


FRONTEND_PATH = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


def _inline_scripts(markup):
    scripts = re.findall(
        r"<script\b[^>]*>(.*?)</script\s*>",
        markup,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return "\n".join(script for script in scripts if script.strip())


def _load_signal_body(script):
    match = re.search(
        r"async\s+function\s+loadSignal\s*\(\s*\)\s*\{"
        r"(.*?)"
        r"\n\}\s*\n\s*loadSignal\(\);",
        script,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("Could not locate the single loadSignal implementation")
    return match.group(1)


class DashboardReadOnlyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.markup = FRONTEND_PATH.read_text(encoding="utf-8")
        cls.script = _inline_scripts(cls.markup)

    def test_dashboard_has_one_real_signal_refresh_control(self):
        self.assertRegex(
            self.markup,
            r'<button[^>]*id="refresh-signal"[^>]*onclick="loadSignal\(\)"',
        )
        self.assertEqual(
            len(re.findall(r"async\s+function\s+loadSignal\s*\(", self.script)),
            1,
        )
        self.assertNotRegex(self.markup, r"onclick\s*=\s*['\"]signal\(")
        self.assertNotRegex(self.script, r"function\s+signal\s*\(")

    def test_signal_is_loaded_once_and_refreshed_on_a_single_interval(self):
        self.assertEqual(
            len(re.findall(r"^\s*loadSignal\(\);\s*$", self.script, re.MULTILINE)),
            1,
        )
        self.assertEqual(
            len(re.findall(r"setInterval\(\s*loadSignal\s*,", self.script)),
            1,
        )

    def test_dashboard_api_requests_use_the_current_origin(self):
        self.assertNotRegex(
            self.script,
            r"https?://(?:127\.0\.0\.1|localhost):\d+/api/",
        )
        self.assertNotRegex(self.script, r"file://")

    def test_signal_panel_uses_only_the_read_only_analysis_endpoint(self):
        body = _load_signal_body(self.script)
        self.assertIn('fetch("/api/signal/v2")', body)
        self.assertNotRegex(body, r"method\s*:\s*['\"]POST['\"]")
        self.assertNotIn("/api/paper/", body)
        self.assertNotIn("/api/orders", body)
        self.assertIn("Análisis PAPER de solo lectura", body)

    def test_failed_signal_request_is_shown_as_unavailable_not_a_fake_signal(self):
        body = _load_signal_body(self.script)
        self.assertIn("!response.ok || data.error || !data.signal", body)
        self.assertIn("Análisis no disponible:", body)
        self.assertNotIn('data.signal || "NEUTRAL"', body)

    def test_signal_panel_renders_risk_levels_and_cost_context(self):
        body = _load_signal_body(self.script)
        for expected in (
            "data.signal",
            "data.score",
            "data.entry",
            "data.stop_loss",
            "data.take_profit_1",
            "data.take_profit_2",
            "data.invalidation?.price",
            "regime.cost_in_r",
            "data.reasons",
        ):
            with self.subTest(field=expected):
                self.assertIn(expected, body)


if __name__ == "__main__":
    unittest.main()
