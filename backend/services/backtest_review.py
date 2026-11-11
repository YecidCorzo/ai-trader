from skills.backtest_expert.evaluate_backtest import evaluate


def _candle_timestamp(candle):
    if isinstance(candle, dict):
        return candle.get("time", candle.get("timestamp"))
    if isinstance(candle, (list, tuple)) and candle:
        return candle[0]
    return None


def review_backtest(result, candles, parameter_count=8):
    trades = result.get("trades", [])
    winners = [trade for trade in trades if float(trade.get("net_pnl", 0)) > 0]
    losers = [trade for trade in trades if float(trade.get("net_pnl", 0)) < 0]

    def average_return_pct(items):
        returns = []
        for trade in items:
            entry = float(trade.get("entry", 0))
            quantity = float(trade.get("quantity", 0))
            notional = entry * quantity
            if notional > 0:
                returns.append(float(trade.get("net_pnl", 0)) / notional * 100)
        return sum(returns) / len(returns) if returns else 0.0

    years_tested = 0.0
    if len(candles) >= 2:
        first = _candle_timestamp(candles[0])
        last = _candle_timestamp(candles[-1])
        if first is not None and last is not None:
            divisor = 1000 if float(last) > 10_000_000_000 else 1
            years_tested = max(0.0, (float(last) - float(first)) / divisor / 31_557_600)

    total_trades = len(trades)
    win_rate = result.get("win_rate_percent")
    if win_rate is None:
        win_rate = (len(winners) / total_trades * 100) if total_trades else 0.0

    evaluation = evaluate(
        total_trades=total_trades,
        win_rate=float(win_rate),
        avg_win_pct=average_return_pct(winners),
        avg_loss_pct=abs(average_return_pct(losers)),
        max_drawdown_pct=float(result.get("max_drawdown_percent", 0)),
        years_tested=int(years_tested),
        num_parameters=parameter_count,
        slippage_tested=float(result.get("slippage_rate", 0)) > 0,
    )

    # A single aggregate backtest cannot establish the multiple independent
    # chronological out-of-sample windows required by this project's research
    # protocol. Never translate a generic score into a deployment instruction.
    research_blockers = []
    if total_trades < 100:
        research_blockers.append("fewer_than_100_trades")
    if years_tested < 5:
        research_blockers.append("less_than_5_years")
    if float(result.get("max_drawdown_percent", 0)) >= 20:
        research_blockers.append("drawdown_at_or_above_20_percent")
    if evaluation["expectancy"] <= 0:
        research_blockers.append("non_positive_expectancy")
    profit_factor = result.get("profit_factor")
    if profit_factor is None or float(profit_factor) <= 1.2:
        research_blockers.append("profit_factor_not_above_1_2")
    research_blockers.append("multiple_out_of_sample_windows_not_verified")

    return {
        "framework": "ai_trader_research_gates",
        "years_tested_exact": round(years_tested, 6),
        "live_trading_authorized": False,
        "scorecard": evaluation,
        "decision": "VALIDATION_REQUIRED",
        "blocking_reasons": research_blockers,
        "research_gates_passed": False,
        "research_gates_complete": False,
    }
