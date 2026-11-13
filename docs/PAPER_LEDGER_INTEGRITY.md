# PAPER ledger integrity

Migration `0008_paper_ledger_integrity.sql` enforces accounting invariants in SQLite.

- A `TRADE_REALIZED_PNL` event must reference one CLOSED trade in the same PAPER account and exactly match its persisted P&L.
- CLOSED trade financial fields are immutable.
- Account and trade financial values use plain decimal notation with at most 8 fractional places.
- The TradeLedger accepts values with up to 8 fractional places and writes canonical fixed-point decimals; leading zeroes are normalized by Decimal formatting. Direct SQL writes with leading zeroes or excess precision are rejected.
- Monetary values are rounded to 8 places using `ROUND_HALF_EVEN`.

`PaperExecutionService.reconcile_account(account_id)` exposes reconciliation. When `consistent` is false, it returns the `PAPER_LEDGER_INCONSISTENT` alert and halts that account's PAPER circuit breaker.

File-backed SQLite connections use WAL. In-memory test databases retain SQLite's in-memory journal mode.

Run all tests from the repository root:

```bash
pytest -q
PYTHONPATH=backend python -m unittest discover -s tests -v
```

All behavior remains PAPER-only. No live orders, exchange credentials, or real funds are introduced.
