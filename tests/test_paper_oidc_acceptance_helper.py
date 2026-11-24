"""Tests for the provider-backed PAPER OIDC acceptance helper."""

import base64
import json
import unittest

from decimal import Decimal

from scripts.verify_paper_oidc_ownership import (
    _assert_account_state_unchanged,
    _ensure_distinct_test_identities,
)


def make_token(*, issuer="https://keycloak.test/realms/ai-trader", subject="user-a"):
    payload = json.dumps({"iss": issuer, "sub": subject}).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


class PaperOidcAcceptanceHelperTests(unittest.TestCase):
    @staticmethod
    def state():
        account = {
            "balance": "1000.00000000",
            "equity": "1000.00000000",
            "free_cash": "1000.00000000",
            "open_positions": [],
            "live_trading_authorized": False,
        }
        risk = {"halted": False, "reason": None}
        events = {"account_events": [{"event_type": "OPENING_CAPITAL", "amount": "1000.00000000"}],
                  "trade_events": []}
        trades = {"trades": []}
        return account, risk, events, trades

    def assert_state_rejected(self, *, account=None, risk=None, events=None, trades=None, message):
        before_account, before_risk, before_events, before_trades = self.state()
        after_account = before_account if account is None else account
        after_risk = before_risk if risk is None else risk
        after_events = before_events if events is None else events
        after_trades = before_trades if trades is None else trades
        with self.assertRaisesRegex(RuntimeError, message):
            _assert_account_state_unchanged(
                before_account, after_account,
                before_risk, after_risk,
                before_events, after_events,
                before_trades, after_trades,
            )

    def test_accepts_unchanged_financial_and_audit_state(self):
        account, risk, events, trades = self.state()
        _assert_account_state_unchanged(
            account, dict(account), risk, dict(risk),
            events, dict(events), trades, dict(trades),
        )

    def test_detects_equity_or_free_cash_change_even_when_balance_is_unchanged(self):
        account, _, _, _ = self.state()
        self.assert_state_rejected(
            account={**account, "equity": "999.99"},
            message="balance/equity/free_cash",
        )
        self.assert_state_rejected(
            account={**account, "free_cash": "999.99"},
            message="balance/equity/free_cash",
        )

    def test_detects_circuit_breaker_mutation(self):
        self.assert_state_rejected(
            risk={"halted": True, "reason": "unauthorized"},
            message="circuit breaker",
        )

    def test_detects_ledger_event_mutation(self):
        self.assert_state_rejected(
            events={"account_events": [{"event_type": "OPENING_CAPITAL", "amount": "1000"},
                                       {"event_type": "DEPOSIT", "amount": "1"}],
                    "trade_events": []},
            message="ledger",
        )

    def test_detects_trade_history_mutation(self):
        self.assert_state_rejected(
            trades={"trades": [{"id": "unexpected-trade", "status": "OPEN"}]},
            message="historial de operaciones",
        )

    def test_rejects_non_finite_financial_values(self):
        account, risk, events, trades = self.state()
        with self.assertRaisesRegex(RuntimeError, "no finito"):
            _assert_account_state_unchanged(
                account, {**account, "equity": "NaN"},
                risk, risk, events, events, trades, trades,
            )

    def test_accepts_distinct_subjects_from_same_issuer(self):
        _ensure_distinct_test_identities(
            make_token(subject="user-a"),
            make_token(subject="user-b"),
        )

    def test_rejects_different_tokens_for_same_subject(self):
        first = make_token(subject="user-a")
        payload = first.split(".")[1]
        second = f"another-header.{payload}.another-signature"
        with self.assertRaisesRegex(ValueError, "mismo subject"):
            _ensure_distinct_test_identities(first, second)

    def test_rejects_different_issuers(self):
        with self.assertRaisesRegex(ValueError, "mismo issuer"):
            _ensure_distinct_test_identities(
                make_token(issuer="https://issuer-a.test", subject="user-a"),
                make_token(issuer="https://issuer-b.test", subject="user-b"),
            )

    def test_rejects_non_jwt_token(self):
        with self.assertRaisesRegex(ValueError, "formato JWT"):
            _ensure_distinct_test_identities("opaque-token-a", "opaque-token-b")

    def test_rejects_missing_subject(self):
        payload = base64.urlsafe_b64encode(
            json.dumps({"iss": "https://keycloak.test/realms/ai-trader"}).encode()
        ).decode().rstrip("=")
        token_without_subject = f"header.{payload}.signature"
        with self.assertRaisesRegex(ValueError, "subject válido"):
            _ensure_distinct_test_identities(
                token_without_subject,
                make_token(subject="user-b"),
            )

    def test_rejects_malformed_jwt_payload(self):
        with self.assertRaisesRegex(ValueError, "leer los claims"):
            _ensure_distinct_test_identities(
                "header.bm90LWpzb24.signature",
                make_token(subject="user-b"),
            )


if __name__ == "__main__":
    unittest.main()
