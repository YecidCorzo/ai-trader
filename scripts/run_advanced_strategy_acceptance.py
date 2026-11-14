#!/usr/bin/env python3
"""Run the frozen AdvancedStrategy acceptance sample on public Binance history."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from services.market_services import MarketService
from services.backtest_research import run_advanced_strategy_walk_forward_backtests
from services.strategy_acceptance import (
    ADVANCED_STRATEGY_ACCEPTANCE_CONFIG,
    evaluate_advanced_strategy_go_no_go,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/advanced_strategy_acceptance.json",
        help="Path for the complete JSON report",
    )
    args = parser.parse_args()

    config = dict(ADVANCED_STRATEGY_ACCEPTANCE_CONFIG)
    market = MarketService(config["market_symbol"])
    candles = market.get_candles(
        interval=config["interval"],
        limit=config["limit"],
        closed_only=True,
    )
    candles = candles[-config["limit"]:]
    history_count = len(candles)

    if history_count >= config["required_bars"]:
        walk_forward = run_advanced_strategy_walk_forward_backtests(
            candles,
            train_size=config["train_size"],
            validation_size=config["validation_size"],
            test_size=config["test_size"],
            step_size=config["step_size"],
            backtest_kwargs={
                "initial_balance": 10000.0,
                "fee_rate": 0.001,
                "slippage_rate": 0.0005,
                "risk_per_trade": 0.01,
            },
        )
    else:
        walk_forward = {
            "framework": "fixed_parameter_advanced_strategy_chronological_walk_forward",
            "strategy": "AdvancedStrategy",
            "mode": "paper",
            "parameter_optimization_performed": False,
            "fold_count": 0,
            "total_trades": 0,
            "expectancy_per_trade": None,
            "profit_factor": None,
            "max_fold_drawdown_percent": None,
            "folds": [],
            "trades": [],
            "limitations": [
                "Insufficient real closed-candle history for the pre-registered sample",
                "No OOS folds were run",
            ],
        }

    decision = evaluate_advanced_strategy_go_no_go(walk_forward)
    report = {
        "report_generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID"),
        "github_run_number": os.environ.get("GITHUB_RUN_NUMBER"),
        "git_commit": os.environ.get("GITHUB_SHA"),
        "mode": "paper",
        "acceptance_config": config,
        "symbol": config["symbol"],
        "market_symbol": config["market_symbol"],
        "interval": config["interval"],
        "candles_requested": config["limit"],
        "candles_received": history_count,
        "history_complete": history_count >= config["limit"],
        "history_start": candles[0][0] if candles else None,
        "history_end": candles[-1][0] if candles else None,
        "decision": decision,
        "walk_forward": walk_forward,
        "safety": {
            "exchange_credentials_used": False,
            "exchange_orders_submitted": False,
            "live_trading_authorized": False,
            "data_source": "Binance public market data only",
        },
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, indent=2, sort_keys=True, default=str)
    output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    # NO_GO is a valid research outcome and must still publish the full report.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
