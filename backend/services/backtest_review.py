"""Conservative, deterministic review gates for PAPER backtests.

This adapts the decision-gate philosophy of Claude Trading Skills' Backtest
Expert. It does not reproduce its proprietary scoring script and never
authorizes live trading.
"""
from datetime import datetime, timezone


def review_backtest(result, candles, parameter_count=6):
    trades = result.get("trades", [])
    total_trades = len(trades)
    blocking_reasons = []
    warnings = []
    red_flags = []

    if total_trades < 30:
        decision = "NOT_EVALUABLE"
        blocking_reasons.append("Insufficient sample: fewer than 30 closed trades.")
    else:
        profit_factor = result.get("profit_factor")
        drawdown = float(result.get("max_drawdown_percent", 0))
        if profit_factor is not None and float(profit_factor) < 1:
            decision = "REJECT"
            blocking_reasons.append("Negative expectancy: profit factor is below 1.0.")
        elif drawdown >= 50:
            decision = "REJECT"
            blocking_reasons.append("Maximum drawdown is at least 50%.")
        else:
            decision = "REFINE"

    if len(candles) >= 2:
        first = candles[0].get("time")
        last = candles[-1].get("time")
        if first is not None and last is not None:
            # Binance timestamps may be milliseconds or seconds.
            divisor = 1000 if float(last) > 10_000_000_000 else 1
            years_tested = max(0.0, (float(last) - float(first)) / divisor / 31_557_600)
        else:
            years_tested = None
    else:
        years_tested = None

    if years_tested is None:
        warnings.append("Historical coverage could not be established from candle timestamps.")
    elif years_tested < 5:
        warnings.append("Historical test period is shorter than five years.")

    if parameter_count >= 7:
        red_flags.append("High parameter count increases curve-fitting risk.")
    if not result.get("slippage_rate"):
        warnings.append("Slippage is not modeled or is set to zero.")
    if float(result.get("max_drawdown_percent", 0)) >= 30:
        red_flags.append("Severe drawdown: at least 30%.")

    winners = [t for t in trades if float(t.get("net_pnl", 0)) > 0]
    losers = [t for t in trades if float(t.get("net_pnl", 0)) <= 0]
    avg_win = sum(float(t["net_pnl"]) for t in winners) / len(winners) if winners else 0.0
    avg_loss = abs(sum(float(t["net_pnl"]) for t in losers) / len(losers)) if losers else 0.0

    if decision == "REFINE" and (years_tested is None or years_tested < 5):
        decision = "VALIDATION_REQUIRED"

    return {
        "framework": "backtest_expert_adapted",
        "decision": decision,
        "live_trading_authorized": False,
        "total_trades": total_trades,
        "years_tested": round(years_tested, 4) if years_tested is not None else None,
        "parameter_count": parameter_count,
        "average_winner_net_pnl": round(avg_win, 4),
        "average_loser_net_pnl": round(avg_loss, 4),
        "profit_factor": result.get("profit_factor"),
        "max_drawdown_percent": result.get("max_drawdown_percent"),
        "fee_rate": result.get("fee_rate"),
        "slippage_rate": result.get("slippage_rate"),
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "red_flags": red_flags,
    }
