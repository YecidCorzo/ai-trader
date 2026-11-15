#!/usr/bin/env python3
"""Pre-registered nine-symbol AdvancedStrategy PAPER acceptance v2."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from services.market_services import MarketService
from services.backtest_research import run_advanced_strategy_walk_forward_backtests
from services.strategy_acceptance import evaluate_advanced_strategy_go_no_go
from strategies.advanced_strategy import AdvancedStrategy

CONFIG = {
    "config_id": "ADV-MULTI-9USDT-1H-10000-5000-1000-1000-1000-v2",
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
                "DOGEUSDT", "LINKUSDT", "LTCUSDT", "AVAXUSDT"],
    "interval": "1h", "limit": 10000, "train_size": 5000,
    "validation_size": 1000, "test_size": 1000, "step_size": 1000,
    "required_bars": 7000, "expected_folds": 4,
    "initial_balance_per_symbol_fold": 10000.0,
    "fee_rate": 0.001, "slippage_rate": 0.0005, "risk_per_trade": 0.01,
    "strategy": {
        "min_score": 60, "atr_stop_multiplier": 1.5, "risk_reward": 2.0,
        "min_atr_percent": None, "max_atr_percent": 0.05,
        "min_ema_slope_percent": 0.0001, "min_volume_ratio": 1.0,
        "volume_mean_period": 20, "fee_rate": 0.001,
        "slippage_rate": 0.0005, "max_cost_r": 0.15,
    },
}
HOUR_MS = 3_600_000


def histories_are_aligned(candles_by_symbol):
    """Require the exact same uninterrupted hourly timestamp sequence per pair."""
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


def _pf(trades):
    wins = sum(float(t["net_pnl"]) for t in trades if float(t["net_pnl"]) > 0)
    losses = abs(sum(float(t["net_pnl"]) for t in trades if float(t["net_pnl"]) < 0))
    return round(wins / losses, 6) if losses else None


def aggregate_symbol_results(symbol_runs, candles_by_symbol):
    """Pool trades; drawdown is max individual symbol/fold DD, not portfolio DD."""
    if set(symbol_runs) != set(CONFIG["symbols"]):
        raise ValueError("Universe differs from the pre-registered symbol set")
    nfolds = CONFIG["expected_folds"]
    all_trades, symbol_summaries = [], {}
    by_fold = {i: [] for i in range(1, nfolds + 1)}
    dd_by_fold = {i: [] for i in range(1, nfolds + 1)}
    for symbol in CONFIG["symbols"]:
        result, candles = symbol_runs[symbol], candles_by_symbol[symbol]
        folds, trades = result.get("folds", []), result.get("trades", [])
        if len(folds) != nfolds or len(trades) != result.get("total_trades"):
            raise ValueError(f"{symbol}: fold/trade ledger mismatch")
        symbol_summaries[symbol] = {
            key: result[key] for key in (
                "total_trades", "net_pnl", "expectancy_per_trade", "profit_factor",
                "max_fold_drawdown_percent", "total_fees", "average_cost_in_r"
            )
        }
        symbol_tagged_trades = []
        for fold in folds:
            number = int(fold["fold"])
            start, end = fold["test_range"]
            start_ms = int(candles[start][0])
            end_ms = int(candles[end][0]) if end < len(candles) else int(candles[-1][0]) + HOUR_MS
            dd_by_fold[number].append(float(fold["max_drawdown_percent"]))
            matching = []
            for trade in trades:
                if start_ms <= int(trade["entry_time"]) < end_ms:
                    matching.append(dict(trade, symbol=symbol, fold=number))
            if len(matching) != int(fold["trade_count"]):
                raise ValueError(f"{symbol} fold {number}: trade attribution mismatch")
            by_fold[number].extend(matching)
            symbol_tagged_trades.extend(matching)
        all_trades.extend(symbol_tagged_trades)

    pooled_folds = []
    for number in range(1, nfolds + 1):
        trades = by_fold[number]
        pnl = sum(float(t["net_pnl"]) for t in trades)
        pooled_folds.append({
            "fold": number, "trade_count": len(trades), "net_pnl": round(pnl, 6),
            "expectancy_per_trade": round(pnl / len(trades), 6) if trades else None,
            "profit_factor": _pf(trades),
            "max_drawdown_percent": round(max(dd_by_fold[number]), 6),
            "drawdown_aggregation": "maximum_across_independent_symbol_folds",
        })
    count = len(all_trades)
    pnl = sum(float(t["net_pnl"]) for t in all_trades)
    gross_profit = sum(float(t["net_pnl"]) for t in all_trades if float(t["net_pnl"]) > 0)
    gross_loss = abs(sum(float(t["net_pnl"]) for t in all_trades if float(t["net_pnl"]) < 0))
    return {
        "framework": "fixed_parameter_multi_symbol_chronological_walk_forward",
        "strategy": "AdvancedStrategy", "mode": "paper",
        "parameter_optimization_performed": False,
        "symbol_count": len(CONFIG["symbols"]), "symbols": list(CONFIG["symbols"]),
        "fold_count": nfolds,
        "initial_balance_per_symbol_fold": CONFIG["initial_balance_per_symbol_fold"],
        "aggregation": "pooled_trade_outcomes_across_independent_symbol_fold_simulations; not a portfolio equity curve",
        "total_trades": count, "net_pnl": round(pnl, 6),
        "expectancy_per_trade": round(pnl / count, 6) if count else None,
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
        "max_fold_drawdown_percent": round(max(f["max_drawdown_percent"] for f in pooled_folds), 6),
        "total_fees": round(sum(float(v["total_fees"]) for v in symbol_summaries.values()), 6),
        "average_cost_in_r": round(sum(float(t["cost_in_r"]) for t in all_trades) / count, 6) if count else None,
        "folds": pooled_folds, "symbol_summaries": symbol_summaries, "trades": all_trades,
        "limitations": [
            "each symbol/fold starts with independent virtual capital; pooled PnL is not portfolio return",
            "drawdown is maximum individual symbol/fold drawdown, not simultaneous portfolio drawdown",
            "OHLC execution and intrabar ordering remain simplified PAPER assumptions",
            "strategy parameters and 0.15R cost filter are frozen; no OOS optimization",
            "this research result does not authorize DEMO or LIVE exchange orders",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/advanced_strategy_acceptance_multi_symbol_v2.json")
    args = parser.parse_args()
    report = {
        "report_generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_number": os.environ.get("GITHUB_RUN_NUMBER"),
        "git_commit": os.environ.get("GITHUB_SHA"), "mode": "paper",
        "acceptance_config": CONFIG, "history_complete": False,
        "timestamp_alignment_passed": False, "symbol_history": {},
        "data_errors": [], "decision": None, "walk_forward": None,
        "safety": {"exchange_credentials_used": False, "exchange_orders_submitted": False,
                   "live_trading_authorized": False, "data_source": "Binance public market data only"},
    }
    candles_by_symbol = {}
    for symbol in CONFIG["symbols"]:
        try:
            candles = MarketService(symbol).get_candles(
                interval=CONFIG["interval"], limit=CONFIG["limit"], closed_only=True
            )[-CONFIG["limit"]:]
            candles_by_symbol[symbol] = candles
            report["symbol_history"][symbol] = {
                "candles_requested": CONFIG["limit"], "candles_received": len(candles),
                "history_complete": len(candles) == CONFIG["limit"],
                "history_start": int(candles[0][0]) if candles else None,
                "history_end": int(candles[-1][0]) if candles else None,
            }
            if len(candles) != CONFIG["limit"]:
                report["data_errors"].append(f"{symbol}: incomplete closed-candle history")
        except Exception as error:
            report["data_errors"].append(f"{symbol}: {type(error).__name__}: {error}")
    complete = len(candles_by_symbol) == len(CONFIG["symbols"]) and all(
        report["symbol_history"].get(s, {}).get("history_complete", False) for s in CONFIG["symbols"]
    )
    report["history_complete"] = complete
    if complete:
        report["timestamp_alignment_passed"] = histories_are_aligned(candles_by_symbol)
        if not report["timestamp_alignment_passed"]:
            report["data_errors"].append(
                "Symbol histories are not identical, uninterrupted hourly timestamp sequences"
            )
    scored = False
    if complete and report["timestamp_alignment_passed"]:
        try:
            strategy = AdvancedStrategy(**CONFIG["strategy"])
            kwargs = {
                "initial_balance": CONFIG["initial_balance_per_symbol_fold"],
                "fee_rate": CONFIG["fee_rate"], "slippage_rate": CONFIG["slippage_rate"],
                "risk_per_trade": CONFIG["risk_per_trade"], "strategy": strategy,
            }
            runs = {
                symbol: run_advanced_strategy_walk_forward_backtests(
                    candles_by_symbol[symbol], train_size=CONFIG["train_size"],
                    validation_size=CONFIG["validation_size"], test_size=CONFIG["test_size"],
                    step_size=CONFIG["step_size"], backtest_kwargs=kwargs,
                ) for symbol in CONFIG["symbols"]
            }
            walk = aggregate_symbol_results(runs, candles_by_symbol)
            report["walk_forward"] = walk
            report["decision"] = evaluate_advanced_strategy_go_no_go(walk)
            scored = True
        except Exception as error:
            report["data_errors"].append(
                f"Scoring/aggregation failed closed: {type(error).__name__}: {error}"
            )
    if not scored:
        blocked = {
            "framework": "fixed_parameter_multi_symbol_chronological_walk_forward",
            "strategy": "AdvancedStrategy", "mode": "paper",
            "parameter_optimization_performed": False, "fold_count": 0,
            "total_trades": 0, "expectancy_per_trade": None, "profit_factor": None,
            "max_fold_drawdown_percent": None, "folds": [], "trades": [],
            "limitations": ["Data completeness/alignment failed; no OOS scoring was performed"],
        }
        report["walk_forward"] = blocked
        report["decision"] = evaluate_advanced_strategy_go_no_go(blocked)
        report["decision"]["decision"] = "NO_GO"
        report["decision"]["data_integrity_blocked"] = True
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, indent=2, sort_keys=True, default=str)
    output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
