#!/usr/bin/env python3
"""Fixed-parameter diagnostics across train, validation and untouched OOS windows.

This is descriptive research only: it does not sweep or alter strategy parameters,
select symbols, or change the frozen acceptance thresholds.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path

from services.market_services import MarketService
from services.advanced_strategy_backtest import AdvancedStrategyBacktestService
from strategies.advanced_strategy import AdvancedStrategy

CONFIG = {
    "config_id": "ADV-MULTI-9USDT-1H-10000-5000-1000-1000-1000-v2",
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
                "DOGEUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT"],
    "interval": "1h",
    "limit": 10000,
    "train_size": 5000,
    "validation_size": 1000,
    "test_size": 1000,
    "step_size": 1000,
    "initial_balance_per_symbol_window": 10000.0,
    "fee_rate": 0.001,
    "slippage_rate": 0.0005,
    "risk_per_trade": 0.01,
    "strategy": {
        "min_score": 60,
        "atr_stop_multiplier": 1.5,
        "risk_reward": 2.0,
        "min_atr_percent": None,
        "max_atr_percent": 0.05,
        "min_ema_slope_percent": 0.0001,
        "min_volume_ratio": 1.0,
        "volume_mean_period": 20,
        "fee_rate": 0.001,
        "slippage_rate": 0.0005,
        "max_cost_r": 0.15,
    },
}
HOUR_MS = 3_600_000


def histories_are_aligned(candles_by_symbol):
    if set(candles_by_symbol) != set(CONFIG["symbols"]):
        return False
    reference = None
    for symbol in CONFIG["symbols"]:
        candles = candles_by_symbol[symbol]
        if len(candles) != CONFIG["limit"]:
            return False
        timestamps = [int(row[0]) for row in candles]
        if any(right - left != HOUR_MS for left, right in zip(timestamps, timestamps[1:])):
            return False
        if reference is None:
            reference = timestamps
        elif timestamps != reference:
            return False
    return True


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _group_metrics(trades, key):
    groups = defaultdict(list)
    for trade in trades:
        groups[str(trade.get(key, "unknown"))].append(trade)
    output = {}
    for name, items in sorted(groups.items()):
        pnl = sum(float(item["net_pnl"]) for item in items)
        winners = sum(float(item["net_pnl"]) > 0 for item in items)
        output[name] = {
            "trade_count": len(items),
            "net_pnl": round(pnl, 6),
            "expectancy_per_trade": round(pnl / len(items), 6),
            "win_rate_percent": round(winners / len(items) * 100, 4),
        }
    return output


def summarize_trades(trades, max_drawdown_percent=None):
    """Summarize independent simulation outcomes; not a portfolio equity curve."""
    values = []
    for trade in trades:
        pnl = _number(trade.get("net_pnl"))
        if pnl is None:
            raise ValueError("Trade ledger contains missing or non-finite net_pnl")
        values.append((trade, pnl))
    count = len(values)
    total_pnl = sum(pnl for _, pnl in values)
    gross_profit = sum(pnl for _, pnl in values if pnl > 0)
    gross_loss = abs(sum(pnl for _, pnl in values if pnl < 0))
    wins = sum(pnl > 0 for _, pnl in values)
    fees = sum(
        (_number(trade.get("entry_fee")) or 0.0)
        + (_number(trade.get("exit_fee")) or 0.0)
        for trade, _ in values
    )
    def mean_metric(field):
        numbers = [_number(trade.get(field)) for trade, _ in values]
        numbers = [value for value in numbers if value is not None]
        return round(sum(numbers) / len(numbers), 6) if numbers else None

    return {
        "trade_count": count,
        "net_pnl": round(total_pnl, 6),
        "expectancy_per_trade": round(total_pnl / count, 6) if count else None,
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
        "win_rate_percent": round(wins / count * 100, 4) if count else None,
        "total_fees": round(fees, 6),
        "average_cost_in_r": mean_metric("cost_in_r"),
        "average_mfe_r": mean_metric("mfe_r"),
        "average_mae_r": mean_metric("mae_r"),
        "tp1_hit_rate_percent": round(
            sum(bool(trade.get("tp1_hit")) for trade, _ in values) / count * 100, 4
        ) if count else None,
        "tp2_hit_rate_percent": round(
            sum(bool(trade.get("tp2_hit")) for trade, _ in values) / count * 100, 4
        ) if count else None,
        "max_individual_window_drawdown_percent": max_drawdown_percent,
        "by_direction": _group_metrics([trade for trade, _ in values], "direction"),
        "by_exit_reason": _group_metrics([trade for trade, _ in values], "exit_reason"),
        "by_score": _score_groups([trade for trade, _ in values]),
    }


def _score_groups(trades):
    buckets = {"60-79": [], "80-89": [], "90-100": [], "other_or_missing": []}
    for trade in trades:
        score = _number(trade.get("score"))
        if score is None:
            buckets["other_or_missing"].append(trade)
        elif 60 <= score < 80:
            buckets["60-79"].append(trade)
        elif 80 <= score < 90:
            buckets["80-89"].append(trade)
        elif 90 <= score <= 100:
            buckets["90-100"].append(trade)
        else:
            buckets["other_or_missing"].append(trade)
    result = {}
    for label, items in buckets.items():
        if items:
            result[label] = {
                "trade_count": len(items),
                "net_pnl": round(sum(float(item["net_pnl"]) for item in items), 6),
                "expectancy_per_trade": round(
                    sum(float(item["net_pnl"]) for item in items) / len(items), 6
                ),
            }
    return result


def _run_window(candles, start_index, end_index, strategy):
    engine = AdvancedStrategyBacktestService(
        initial_balance=CONFIG["initial_balance_per_symbol_window"],
        fee_rate=CONFIG["fee_rate"],
        slippage_rate=CONFIG["slippage_rate"],
        risk_per_trade=CONFIG["risk_per_trade"],
        strategy=strategy,
    )
    result = engine.run(candles, start_index=start_index, end_index=end_index)
    if result["total_trades"] != len(result["trades"]):
        raise ValueError("Backtest summary and trade ledger count differ")
    return result


def run_diagnostics(candles_by_symbol):
    if not histories_are_aligned(candles_by_symbol):
        raise ValueError("Symbol histories are incomplete or not identically aligned")

    strategy = AdvancedStrategy(**CONFIG["strategy"])
    stages = {
        "train": [],
        "validation": [],
        "oos_all": [],
        "oos_fold_1": [],
        "oos_fold_2": [],
        "oos_fold_3": [],
        "oos_fold_4": [],
    }
    per_symbol = {}
    max_dd = defaultdict(list)

    for symbol in CONFIG["symbols"]:
        candles = candles_by_symbol[symbol]
        symbol_report = {}
        train = _run_window(candles[:5000], 50, 4999, strategy)
        validation = _run_window(candles[:6000], 4999, 5999, strategy)
        for stage_name, result in (("train", train), ("validation", validation)):
            tagged = [dict(trade, symbol=symbol, window=stage_name) for trade in result["trades"]]
            stages[stage_name].extend(tagged)
            max_dd[stage_name].append(float(result["max_drawdown_percent"]))
            symbol_report[stage_name] = {
                key: result[key] for key in (
                    "total_trades", "net_profit", "expectancy_per_trade",
                    "profit_factor", "win_rate_percent", "max_drawdown_percent",
                    "total_fees", "average_mfe_r", "average_mae_r",
                    "tp1_hits", "tp2_hits", "skipped_signals",
                )
            }

        fold_summaries = []
        for fold_number in range(1, 5):
            test_start = 6000 + (fold_number - 1) * 1000
            test_end = test_start + 1000
            fold_result = _run_window(
                candles[:test_end], test_start - 1, test_end - 1, strategy
            )
            stage_name = f"oos_fold_{fold_number}"
            tagged = [
                dict(trade, symbol=symbol, fold=fold_number, window=stage_name)
                for trade in fold_result["trades"]
            ]
            stages[stage_name].extend(tagged)
            stages["oos_all"].extend(tagged)
            max_dd[stage_name].append(float(fold_result["max_drawdown_percent"]))
            max_dd["oos_all"].append(float(fold_result["max_drawdown_percent"]))
            fold_summaries.append({
                "fold": fold_number,
                "trade_count": fold_result["total_trades"],
                "net_pnl": fold_result["net_profit"],
                "expectancy_per_trade": fold_result["expectancy_per_trade"],
                "profit_factor": fold_result["profit_factor"],
                "win_rate_percent": fold_result["win_rate_percent"],
                "max_drawdown_percent": fold_result["max_drawdown_percent"],
                "total_fees": fold_result["total_fees"],
                "average_mfe_r": fold_result["average_mfe_r"],
                "average_mae_r": fold_result["average_mae_r"],
                "tp1_hits": fold_result["tp1_hits"],
                "tp2_hits": fold_result["tp2_hits"],
                "skipped_signals": fold_result["skipped_signals"],
            })
        symbol_report["oos_folds"] = fold_summaries
        per_symbol[symbol] = symbol_report

    stage_reports = {}
    for stage_name, trades in stages.items():
        dd_values = max_dd.get(stage_name, [])
        stage_reports[stage_name] = summarize_trades(
            trades,
            max(dd_values) if dd_values else None,
        )
    return {
        "aggregation": "pooled outcomes across independent symbol/window simulations; not a portfolio equity curve",
        "stage_definitions": {
            "train": "indices [0, 5000); signals from index 50; entries and exits contained in train",
            "validation": "indices [5000, 6000); signal on index 4999 may enter at index 5000",
            "oos_fold_1": "indices [6000, 7000); signal on index 5999 may enter at index 6000",
            "oos_fold_2": "indices [7000, 8000); signal on index 6999 may enter at index 7000",
            "oos_fold_3": "indices [8000, 9000); signal on index 7999 may enter at index 8000",
            "oos_fold_4": "indices [9000, 10000); signal on index 8999 may enter at index 9000",
        },
        "stages": stage_reports,
        "per_symbol": per_symbol,
        "trades": {name: trades for name, trades in stages.items()},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/advanced_strategy_fixed_parameter_diagnostics.json",
    )
    args = parser.parse_args()
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_number": os.environ.get("GITHUB_RUN_NUMBER"),
        "git_commit": os.environ.get("GITHUB_SHA"),
        "mode": "paper",
        "diagnostic_only": True,
        "parameter_optimization_performed": False,
        "acceptance_thresholds_changed": False,
        "history_complete": False,
        "timestamp_alignment_passed": False,
        "symbol_history": {},
        "data_errors": [],
        "config": CONFIG,
        "safety": {
            "exchange_credentials_used": False,
            "exchange_orders_submitted": False,
            "live_trading_authorized": False,
            "data_source": "Binance public market data only",
        },
        "diagnostics": None,
    }
    candles_by_symbol = {}
    for symbol in CONFIG["symbols"]:
        try:
            candles = MarketService(symbol).get_candles(
                interval=CONFIG["interval"], limit=CONFIG["limit"], closed_only=True
            )[-CONFIG["limit"]:]
            candles_by_symbol[symbol] = candles
            report["symbol_history"][symbol] = {
                "candles_requested": CONFIG["limit"],
                "candles_received": len(candles),
                "history_complete": len(candles) == CONFIG["limit"],
                "history_start": int(candles[0][0]) if candles else None,
                "history_end": int(candles[-1][0]) if candles else None,
            }
            if len(candles) != CONFIG["limit"]:
                report["data_errors"].append(f"{symbol}: incomplete closed-candle history")
        except Exception as error:
            report["data_errors"].append(
                f"{symbol}: {type(error).__name__}: {error}"
            )
    complete = len(candles_by_symbol) == len(CONFIG["symbols"]) and all(
        report["symbol_history"].get(symbol, {}).get("history_complete", False)
        for symbol in CONFIG["symbols"]
    )
    report["history_complete"] = complete
    if complete:
        report["timestamp_alignment_passed"] = histories_are_aligned(candles_by_symbol)
        if not report["timestamp_alignment_passed"]:
            report["data_errors"].append(
                "Symbol histories are not identical, uninterrupted hourly timestamp sequences"
            )
    if complete and report["timestamp_alignment_passed"]:
        try:
            report["diagnostics"] = run_diagnostics(candles_by_symbol)
        except Exception as error:
            report["data_errors"].append(
                f"Diagnostic run failed closed: {type(error).__name__}: {error}"
            )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, indent=2, sort_keys=True, default=str)
    output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report["diagnostics"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
