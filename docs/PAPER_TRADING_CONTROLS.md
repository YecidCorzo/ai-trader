# Paper trading ledger and risk controls

This module set records simulated trades only. It does not connect to an exchange
account, submit orders, transfer funds, or enable live trading.

## Trade ledger

```python
from backend.infrastructure.database import connect_database, apply_migrations
from backend.services.trade_ledger import TradeLedger

connection = connect_database()
apply_migrations(connection)
ledger = TradeLedger(connection)
```

- Opening and closing prices, quantities and fees are stored as decimal strings.
- Realized P&L is calculated with `Decimal`, including entry and exit fees.
- LONG and SHORT calculations are supported.
- Opening and closing actions produce immutable audit events.
- A closed trade cannot be closed a second time.
- The ledger records simulated fills supplied by a caller; it does not create fills or send orders.

## Risk engine

```python
from decimal import Decimal
from backend.services.risk_engine import RiskEngine, RiskSnapshot

decision = RiskEngine().evaluate(
    RiskSnapshot(equity=Decimal("10000"), planned_loss=Decimal("100"))
)
```

Default conservative limits:
- Maximum planned loss per trade: 1% of current equity.
- Maximum realized daily loss: 3% of current equity.
- Maximum open positions: 1.
- Maximum trades per day: 5.
- Maximum consecutive losses: 3.

The standalone RiskEngine accepts a RiskSnapshot supplied by its caller. The
PaperExecutionService overrides planned loss, open-position count, daily realized
P&L, daily trade count, consecutive-loss count and circuit-breaker state using
the persisted ledger while holding a SQLite write lock. Consecutive-loss ordering
uses the insertion order of immutable close audit events, not second-precision
timestamps or random trade IDs. The caller still supplies equity: this version
has no persisted paper-account capital/equity source, so that value is not
independently verified by the service. Do not use arbitrary or stale equity
values. A risk decision is a gate only; it never submits an order.

## Circuit breaker

```python
from backend.services.circuit_breaker import CircuitBreaker

breaker = CircuitBreaker(connection)
breaker.halt("daily loss limit reached", updated_by="operator")
# Reset is an explicit operator action:
breaker.reset(confirmed_by="operator")
```

The halt state is stored in SQLite and survives application restarts. Reset
requires a non-empty operator confirmation and writes an audit event. The
PaperExecutionService reads this state and records an approved simulated entry
inside the same SQLite write transaction. SQLite's `BEGIN IMMEDIATE` serializes
competing entry attempts against the same database file. A failed risk check or
ledger/audit insert must not create a trade.

## Current boundary

- Mode is always PAPER.
- No live execution or exchange trading credentials.
- No bank integration or movement of money.
- Equity is still caller-supplied; daily P&L, daily trade count, open positions,
  consecutive losses and breaker state are read from persisted PAPER records.
- There is no persisted capital/equity accounting or independent reconciliation
  of the caller-supplied equity amount.
- These controls are not a guarantee against loss and are not a live-trading authorization.
