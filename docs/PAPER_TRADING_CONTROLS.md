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

The caller must supply current equity, planned loss and counters from trusted,
up-to-date paper account state. Missing or stale state must not be treated as zero.
A risk decision is a gate only; it never submits an order.

## Circuit breaker

```python
from backend.services.circuit_breaker import CircuitBreaker

breaker = CircuitBreaker(connection)
breaker.halt("daily loss limit reached", updated_by="operator")
# Reset is an explicit operator action:
breaker.reset(confirmed_by="operator")
```

The halt state is stored in SQLite and survives application restarts. Reset
requires a non-empty operator confirmation and writes an audit event. Integrating
this gate into a future paper execution orchestrator is a separate step; until
then, callers must check the state and risk decision before any simulated entry.

## Current boundary

- Mode is always PAPER.
- No live execution or exchange trading credentials.
- No bank integration or movement of money.
- Risk counters are not yet automatically derived from a complete paper-account
  equity curve; an execution orchestrator must supply verified values.
- These controls are not a guarantee against loss and are not a live-trading authorization.
