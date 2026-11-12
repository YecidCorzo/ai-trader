# PAPER account, trade ledger and risk controls

Everything in this module is simulated. It does not connect to an exchange
account, submit orders, transfer funds, or enable live trading.

## Explicit PAPER account capital

A PAPER account is separate from personal-finance accounts and bank balances.
Creating it requires an explicit opening capital, quote currency and
idempotency key; there is no default balance and no assumed 10,000-unit
starting amount.

```python
from backend.infrastructure.database import apply_migrations, connect_database
from backend.services.paper_account import PaperAccountService

connection = connect_database()
apply_migrations(connection)
accounts = PaperAccountService(connection)  # read-only public Binance ticker
account = accounts.create_account(
    name="Demo account",
    quote_currency="USDT",
    opening_capital="1000",
    idempotency_key="demo-account-opening-v1",
)
print(account["id"])
```

Opening capital, deposits, withdrawals, adjustments and realized trade P&L are
stored as append-only account events. Funding events require an idempotency key;
reusing it with identical data returns the original event, while conflicting
reuse is rejected. Withdrawals cannot exceed the available account balance.
All events must use the account's quote currency.

Existing PAPER trades from before migration 0006 remain unassigned. They are
not attached to a new account, and their history is never used to infer or
invent starting capital.

## Market valuation and equity

The default read-only provider uses Binance's public
`https://data-api.binance.vision/api/v3/ticker/price` endpoint. It needs no API
key or exchange credentials. The exchange response does not provide a trusted
event timestamp, so the application records the local retrieval time; this is
not represented as an exchange-generated timestamp.

Price snapshots are append-only. The default maximum age is 30 seconds.
Missing, malformed, future-dated or stale prices for any open position fail
closed; the service does not silently reuse a stale mark or assume a price.
The provider can be replaced in tests by an injected provider that returns a
`PriceQuote` with a source and timezone-aware retrieval timestamp.

Equity is calculated as:

`account event balance + unrealized P&L on open positions - their entry fees`

Realized P&L is posted to the account ledger in the same SQLite transaction as
the trade-close and audit events. The amount is net of entry and exit fees.
Position marks use Decimal arithmetic and the stored quote currency; the market
symbol's quote asset must match the PAPER account currency. There is no
implicit FX conversion.

```python
equity = accounts.get_equity(account["id"])
print(equity)
```

## Trade ledger and risk gate

```python
from backend.services.paper_execution import PaperExecutionService

execution = PaperExecutionService(connection)
trade = execution.open_position(
    account_id=account["id"],
    symbol="SOLUSDT",
    strategy="ema-rsi",
    side="LONG",
    quantity="1",
    stop_price="95",
    entry_fee="0.1",
    estimated_exit_fee="0.1",
)
# Close at a fresh public market quote; caller cannot supply the exit price.
execution.close_position(
    trade["id"],
    account_id=account["id"],
    exit_fee="0.1",
)
```

The execution service does not accept caller-supplied equity, entry price,
exit price or a
caller-built risk snapshot. The simulated entry fill is taken from a fresh
public market quote; the stop and quantity are validated against that fill.
It derives equity from the selected persisted PAPER account, fresh price
snapshots, and account-scoped trade history while holding a SQLite write lock.
Account IDs scope open positions, daily trade counts, realized
daily P&L and loss streaks. Concurrent entry checks serialize per database;
a failed risk check creates no trade.

Default conservative limits:
- Maximum planned loss per trade: 1% of current account equity.
- Maximum realized daily loss: 3% of current account equity.
- Maximum open positions: 1 per PAPER account.
- Maximum trades per day: 5 per PAPER account.
- Maximum consecutive losses: 3 per PAPER account.

Opening and closing prices, quantities and fees are stored as decimal strings.
LONG and SHORT realized P&L is calculated with Decimal. Opening and closing
actions produce append-only audit events with durable sequence numbers.
Account events and price snapshots also reject updates, deletes and replacement
attempts. A closed trade cannot be closed a second time.

## Circuit breaker

```python
from backend.services.circuit_breaker import CircuitBreaker

breaker = CircuitBreaker(connection, account["id"])
breaker.halt("daily loss limit reached", updated_by="operator")
breaker.reset(confirmed_by="operator")  # explicit operator action
```

The halt state persists in SQLite per PAPER account and reset requires
explicit confirmation. One account's circuit breaker does not halt another
account. The legacy global breaker remains available only for older internal
callers; account-based execution always uses the account-scoped breaker.

## Compatibility and API migration

This release intentionally changes the internal `PaperExecutionService`
contract. It is a breaking change for callers written against the earlier
ledger-only service; there is no unsafe compatibility shim for caller-supplied
fills or risk snapshots.

| Earlier calling pattern | Current contract |
| --- | --- |
| Open with a caller-provided entry price or risk snapshot | `open_position(account_id=..., symbol=..., strategy=..., side=..., quantity=..., stop_price=...)`; entry price and equity are derived internally |
| Close with `close_position(trade_id, exit_price=...)` | `close_position(trade_id, account_id=..., exit_fee=...)`; exit price is obtained from a fresh public market quote |
| Global circuit-breaker calls | Pass `account_id` to `circuit_breaker_status`, `halt` and `reset_circuit_breaker` |

Before upgrading, update every internal caller and test to supply the PAPER
account ID. Create that account with explicit opening capital and a stable
idempotency key. Do not pass an entry/exit price, caller-computed equity or a
caller-built risk snapshot. If a caller cannot be migrated, it must remain
disabled rather than fall back to the previous, less-trusted contract.

The canonical trading symbol format is Binance Spot `BASEQUOTE` (for example
`SOLUSDT`), uppercase ASCII letters/digits with no slash, dash or whitespace.
The quote asset must be one of the quote assets supported by this service and
must exactly match the PAPER account currency. Binance remains the final
authority on whether the complete pair is listed. No implicit FX conversion
or ambiguous suffix matching is performed.

## Current security boundary

- The dashboard reports no balance/equity and an unconfigured account until
  explicit PAPER capital exists; it does not display a fabricated 10,000-unit balance.
- PAPER only; no real funds, bank integration, exchange credentials or live orders.
- No HTTP execution/account routes are exposed by this change.
- Authentication and authorization for multi-user account ownership must be
  designed and reviewed before any account or execution route is added.
- A PAPER account is a simulation, not a real exchange wallet or custody balance.
- Binance retrieval time is a local receive timestamp, not an exchange event time.
- Stale/unavailable prices block valuation and new entries when open positions
  need marking; no fallback to stale data is permitted.
- This is a risk-control gate, not a guarantee against loss or a live-trading authorization.
