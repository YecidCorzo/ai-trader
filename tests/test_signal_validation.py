import unittest

from services.signal_validation import validate_signal_history


class SignalHistoryValidationTests(unittest.TestCase):
    def test_accepts_sufficient_closed_history(self):
        self.assertTrue(validate_signal_history([100.0] * 50, minimum=50))

    def test_rejects_insufficient_history_with_actionable_detail(self):
        with self.assertRaisesRegex(ValueError, "3 available, 50 required"):
            validate_signal_history([100.0] * 3, minimum=50)

    def test_rejects_invalid_minimum(self):
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_signal_history([100.0] * 10, minimum=value)


if __name__ == "__main__":
    unittest.main()
