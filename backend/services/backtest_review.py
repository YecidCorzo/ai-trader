from datetime import datetime, timezone
from skills.backtest_expert.evaluate_backtest import evaluate


def review_backtest(result, candles, parameter_count=8):
    trades = result.get("trades", [])
    winners = [t for t in trades if float(t.get("net_pnl", 0)) > 0]
    losers = [t for t in trades if float(t.get("net_pnl", 0)) < 0]

    def average_return_pct(items):
        returns = []
        for trade in items:
            notional = float(trade.get("entry", 0)) * float(trade.get("quantity", 0))
            if notional > 0:
                returns.append(float(trade.get("net_pnl", 0)) / notional * 100)
        return sum(returns) / len(returns) if returns else 0.0

    if len(candles) >= 2:
        first = candles[0].get("time")
        last = candles[-1].get("time")
        if first is not None and last is not None:
            divisor = 1000 if float(last) > 10_000_000_000 else 1
            years_tested = max(0.0, (float(last) - float(first)) / divisor / 31_557_600)
        else:
            years_tested = 0.0
    else:
        years_tested = 0.0

    # This skill's rubric expects positive average loss magnitude and returns
    # expressed as percentages of entry notional, not raw USDT PnL.
    win_rate = float(result.get("win_rate_percent", 0))
    avg_win_pct = average_return_pct(winners)
    avg_loss_pct = abs(average_return_pct(losers))
    slippage_tested = float(result.get("slippage_rate", 0)) > 0

    evaluation = evaluate(
        total_trades=len(trades),
        win_rate=win_rate,
        avg_win_pct=avg_win_pct,
        avg_loss_pct=avg_loss_pct,
        max_drawdown_pct=float(result.get("max_drawdown_percent", 0)),
        years_tested=int(years_tested),
        num_parameters=parameter_count,
        slippage_tested=slippage_tested,
    )

    return {
        "framework": "claude_trading_skills_backtest_expert",
        "years_tested_exact": round(years_tested, 6),
        "live_trading_authorized": False,
        **evaluation,
    }
