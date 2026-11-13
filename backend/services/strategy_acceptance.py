"""Pre-registered, fail-closed acceptance gates for AdvancedStrategy OOS tests."""
from __future__ import annotations

import math


MIN_OOS_TRADES = 100
MIN_EXPECTANCY_PER_TRADE = 0.0
MIN_PROFIT_FACTOR = 1.20
MAX_DRAWDOWN_PERCENT = 15.0
MIN_WALK_FORWARD_FOLDS = 4
MIN_TRADES_PER_FOLD = 25
MIN_POSITIVE_FOLD_RATIO = 0.75
MIN_FOLD_PROFIT_FACTOR = 1.0


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def evaluate_advanced_strategy_go_no_go(walk_forward):
    """Evaluate fixed gates on AdvancedStrategy walk-forward OOS results.

    Missing/non-finite metrics fail closed. Fold stability requires at least
    75% of folds to have >=25 trades, positive expectancy and PF > 1.0.
    """
    if not isinstance(walk_forward, dict):
        walk_forward = {}

    total_trades = walk_forward.get("total_trades")
    if not isinstance(total_trades, int) or isinstance(total_trades, bool):
        total_trades = None
    expectancy = _number(walk_forward.get("expectancy_per_trade"))
    profit_factor = _number(walk_forward.get("profit_factor"))
    max_drawdown = _number(walk_forward.get("max_fold_drawdown_percent"))
    folds = walk_forward.get("folds")
    if not isinstance(folds, list):
        folds = []

    fold_results = []
    for index, fold in enumerate(folds, start=1):
        if not isinstance(fold, dict):
            fold = {}
        trade_count = fold.get("trade_count")
        if not isinstance(trade_count, int) or isinstance(trade_count, bool):
            trade_count = None
        net_pnl = _number(fold.get("net_pnl"))
        fold_expectancy = _number(fold.get("expectancy_per_trade"))
        if fold_expectancy is None and trade_count and net_pnl is not None:
            fold_expectancy = net_pnl / trade_count
        fold_profit_factor = _number(fold.get("profit_factor"))
        sample_ok = trade_count is not None and trade_count >= MIN_TRADES_PER_FOLD
        profitable = fold_expectancy is not None and fold_expectancy > 0
        pf_ok = fold_profit_factor is not None and fold_profit_factor > MIN_FOLD_PROFIT_FACTOR
        fold_results.append({
            "fold": fold.get("fold", index),
            "trade_count": trade_count,
            "expectancy_per_trade": fold_expectancy,
            "profit_factor": fold_profit_factor,
            "sample_ok": bool(sample_ok),
            "positive_expectancy": bool(profitable),
            "profit_factor_ok": bool(pf_ok),
            "stable": bool(sample_ok and profitable and pf_ok),
        })

    fold_count = len(fold_results)
    positive_folds = sum(1 for fold in fold_results if fold["stable"])
    positive_fold_ratio = positive_folds / fold_count if fold_count else 0.0
    all_folds_have_minimum_sample = bool(fold_count) and all(
        fold["sample_ok"] for fold in fold_results
    )
    if max_drawdown is None and fold_results:
        fold_drawdowns = [
            _number(fold.get("max_drawdown_percent"))
            for fold in folds if isinstance(fold, dict)
        ]
        valid_drawdowns = [value for value in fold_drawdowns if value is not None]
        max_drawdown = max(valid_drawdowns) if valid_drawdowns else None

    criteria = [
        {
            "name": "oos_trade_count",
            "passed": total_trades is not None and total_trades >= MIN_OOS_TRADES,
            "actual": total_trades,
            "required": f">= {MIN_OOS_TRADES}",
        },
        {
            "name": "positive_oos_expectancy",
            "passed": expectancy is not None and expectancy > MIN_EXPECTANCY_PER_TRADE,
            "actual": expectancy,
            "required": "> 0 after fees and slippage",
        },
        {
            "name": "oos_profit_factor",
            "passed": profit_factor is not None and profit_factor >= MIN_PROFIT_FACTOR,
            "actual": profit_factor,
            "required": f">= {MIN_PROFIT_FACTOR:.2f}",
        },
        {
            "name": "maximum_fold_drawdown",
            "passed": max_drawdown is not None and max_drawdown <= MAX_DRAWDOWN_PERCENT,
            "actual": max_drawdown,
            "required": f"<= {MAX_DRAWDOWN_PERCENT:.1f}%",
        },
        {
            "name": "walk_forward_fold_count",
            "passed": fold_count >= MIN_WALK_FORWARD_FOLDS,
            "actual": fold_count,
            "required": f">= {MIN_WALK_FORWARD_FOLDS}",
        },
        {
            "name": "minimum_trades_per_fold",
            "passed": all_folds_have_minimum_sample,
            "actual": [fold["trade_count"] for fold in fold_results],
            "required": f"every fold >= {MIN_TRADES_PER_FOLD}",
        },
        {
            "name": "walk_forward_stability",
            "passed": (
                fold_count >= MIN_WALK_FORWARD_FOLDS
                and positive_fold_ratio >= MIN_POSITIVE_FOLD_RATIO
                and all_folds_have_minimum_sample
            ),
            "actual": {
                "stable_folds": positive_folds,
                "fold_count": fold_count,
                "positive_fold_ratio": round(positive_fold_ratio, 4),
            },
            "required": f">= {MIN_POSITIVE_FOLD_RATIO:.0%} folds with >= {MIN_TRADES_PER_FOLD} trades, positive expectancy and PF > {MIN_FOLD_PROFIT_FACTOR:.1f}",
        },
    ]
    passed = all(item["passed"] for item in criteria)
    return {
        "decision": "GO" if passed else "NO_GO",
        "strategy": "AdvancedStrategy",
        "scope": "chronological_walk_forward_out_of_sample",
        "criteria_passed": sum(1 for item in criteria if item["passed"]),
        "criteria_total": len(criteria),
        "criteria": criteria,
        "folds": fold_results,
        "thresholds": {
            "minimum_oos_trades": MIN_OOS_TRADES,
            "minimum_expectancy_per_trade": MIN_EXPECTANCY_PER_TRADE,
            "minimum_profit_factor": MIN_PROFIT_FACTOR,
            "maximum_fold_drawdown_percent": MAX_DRAWDOWN_PERCENT,
            "minimum_walk_forward_folds": MIN_WALK_FORWARD_FOLDS,
            "minimum_trades_per_fold": MIN_TRADES_PER_FOLD,
            "minimum_positive_fold_ratio": MIN_POSITIVE_FOLD_RATIO,
            "minimum_fold_profit_factor": MIN_FOLD_PROFIT_FACTOR,
        },
        "live_trading_authorized": False,
        "note": "GO significa que se cumplen estos filtros históricos predefinidos; no demuestra rentabilidad futura ni autoriza trading LIVE.",
    }
