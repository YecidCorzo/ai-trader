"""Deterministic pre-trade risk checks for PAPER MODE only."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class RiskLimits:
    max_risk_per_trade: Decimal = Decimal("0.01")
    max_daily_loss: Decimal = Decimal("0.03")
    max_open_positions: int = 1
    max_trades_per_day: int = 5
    max_consecutive_losses: int = 3

    def __post_init__(self) -> None:
        if not self.max_risk_per_trade.is_finite() or not Decimal("0") < self.max_risk_per_trade <= Decimal("0.01"):
            raise ValueError("max_risk_per_trade debe estar entre 0 y 1 %")
        if not self.max_daily_loss.is_finite() or not Decimal("0") < self.max_daily_loss < Decimal("1"):
            raise ValueError("max_daily_loss debe estar entre 0 y 100 %")
        if self.max_open_positions < 1:
            raise ValueError("max_open_positions debe ser al menos 1")
        if self.max_trades_per_day < 1:
            raise ValueError("max_trades_per_day debe ser al menos 1")
        if self.max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses debe ser al menos 1")


@dataclass(frozen=True)
class RiskSnapshot:
    equity: Decimal
    planned_loss: Decimal
    daily_realized_pnl: Decimal = Decimal("0")
    open_positions: int = 0
    trades_today: int = 0
    consecutive_losses: int = 0
    circuit_breaker_halted: bool = False


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    risk_ratio: Decimal | None = None


class RiskEngine:
    """Pure risk gate; it never submits or executes orders."""

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    def evaluate(self, snapshot: RiskSnapshot) -> RiskDecision:
        try:
            values = (
                snapshot.equity,
                snapshot.planned_loss,
                snapshot.daily_realized_pnl,
            )
            if not all(value.is_finite() for value in values):
                return RiskDecision(False, "non_finite_risk_input")
        except (AttributeError, InvalidOperation):
            return RiskDecision(False, "invalid_risk_input")

        if snapshot.circuit_breaker_halted:
            return RiskDecision(False, "circuit_breaker_halted")
        if snapshot.equity <= 0:
            return RiskDecision(False, "equity_must_be_positive")
        if snapshot.planned_loss <= 0:
            return RiskDecision(False, "planned_loss_must_be_positive")
        if min(snapshot.open_positions, snapshot.trades_today, snapshot.consecutive_losses) < 0:
            return RiskDecision(False, "risk_counters_must_not_be_negative")

        risk_ratio = snapshot.planned_loss / snapshot.equity
        if risk_ratio > self.limits.max_risk_per_trade:
            return RiskDecision(False, "per_trade_risk_limit_exceeded", risk_ratio)
        if snapshot.daily_realized_pnl <= -(snapshot.equity * self.limits.max_daily_loss):
            return RiskDecision(False, "daily_loss_limit_reached", risk_ratio)
        if snapshot.open_positions >= self.limits.max_open_positions:
            return RiskDecision(False, "max_open_positions_reached", risk_ratio)
        if snapshot.trades_today >= self.limits.max_trades_per_day:
            return RiskDecision(False, "daily_trade_limit_reached", risk_ratio)
        if snapshot.consecutive_losses >= self.limits.max_consecutive_losses:
            return RiskDecision(False, "consecutive_loss_limit_reached", risk_ratio)

        return RiskDecision(True, "approved", risk_ratio)
