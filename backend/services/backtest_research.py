"""Deterministic research utilities for backtest robustness.

These helpers do not place orders and do not alter the execution engine.
They operate on completed candle/trade records supplied by the caller.
"""
from __future__ import annotations

import math
import random


def _positive_int(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{name} debe ser un entero positivo")


def _finite_number(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} debe ser numérico") from error
    if not math.isfinite(number):
        raise ValueError(f"{name} debe ser finito")
    return number


def chronological_walk_forward_splits(
    candles, train_size, validation_size, test_size, step_size=None
):
    """Return expanding-origin, non-overlapping train/validation/test windows.

    Every split is chronological. Validation and test observations are never
    included in the training slice for the same window. The caller must fit or
    select parameters using train/validation only, then score the untouched test.
    """
    _positive_int(train_size, "train_size")
    _positive_int(validation_size, "validation_size")
    _positive_int(test_size, "test_size")
    if test_size < 2:
        raise ValueError("test_size debe ser al menos 2 para calcular Buy & Hold")
    if step_size is None:
        step_size = test_size
    _positive_int(step_size, "step_size")
    if step_size < test_size:
        raise ValueError(
            "step_size debe ser mayor o igual que test_size para evitar "
            "solapamiento de ventanas fuera de muestra"
        )

    values = list(candles)
    required = train_size + validation_size + test_size
    if len(values) < required:
        raise ValueError(
            f"Se necesitan al menos {required} velas; hay {len(values)}"
        )

    splits = []
    test_start = train_size + validation_size
    while test_start + test_size <= len(values):
        validation_start = test_start - validation_size
        splits.append({
            "train": values[:validation_start],
            "validation": values[validation_start:test_start],
            "test": values[test_start:test_start + test_size],
            "train_range": (0, validation_start),
            "validation_range": (validation_start, test_start),
            "test_range": (test_start, test_start + test_size),
        })
        test_start += step_size
    return splits


def monte_carlo_trade_resampling(
    trades, initial_balance, simulations=1000, seed=42, ruin_drawdown_pct=50.0
):
    """Bootstrap net trade PnL with replacement and report path-risk statistics.

    Ruin is defined as a peak-to-trough drawdown greater than or equal to the
    supplied percentage. This iid trade-order bootstrap does not model regime
    clustering, changing market conditions, or execution beyond recorded PnL.
    """
    _positive_int(simulations, "simulations")
    if simulations > 100_000:
        raise ValueError("simulations no puede superar 100000")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed debe ser un entero")
    balance_start = _finite_number(initial_balance, "initial_balance")
    if balance_start <= 0:
        raise ValueError("initial_balance debe ser positivo")
    threshold = _finite_number(ruin_drawdown_pct, "ruin_drawdown_pct")
    if not 0 < threshold <= 100:
        raise ValueError("ruin_drawdown_pct debe estar entre 0 y 100")

    pnl_values = []
    for index, trade in enumerate(trades):
        if not isinstance(trade, dict) or "net_pnl" not in trade:
            raise ValueError(f"trade[{index}] debe incluir net_pnl")
        pnl_values.append(_finite_number(trade["net_pnl"], f"trade[{index}].net_pnl"))
    if not pnl_values:
        raise ValueError("Se necesita al menos una operación para Monte Carlo")

    rng = random.Random(seed)
    final_balances = []
    max_drawdowns = []
    ruin_count = 0
    sample_size = len(pnl_values)

    for _ in range(simulations):
        balance = balance_start
        peak = balance_start
        max_drawdown = 0.0
        ruined = False
        for _ in range(sample_size):
            balance += rng.choice(pnl_values)
            peak = max(peak, balance)
            drawdown = ((peak - balance) / peak * 100) if peak > 0 else 100.0
            max_drawdown = max(max_drawdown, drawdown)
            if drawdown >= threshold:
                ruined = True
        final_balances.append(balance)
        max_drawdowns.append(max_drawdown)
        ruin_count += int(ruined)

    def percentile(values, percentile_value):
        ordered = sorted(values)
        index = max(0, math.ceil(percentile_value / 100 * len(ordered)) - 1)
        return ordered[index]

    return {
        "method": "iid_trade_pnl_bootstrap",
        "simulations": simulations,
        "seed": seed,
        "trades_per_simulation": sample_size,
        "ruin_definition": f"peak_to_trough_drawdown_gte_{threshold:g}_percent",
        "ruin_probability_percent": round(ruin_count / simulations * 100, 4),
        "final_balance_percentiles": {
            "p05": round(percentile(final_balances, 5), 6),
            "p50": round(percentile(final_balances, 50), 6),
            "p95": round(percentile(final_balances, 95), 6),
        },
        "max_drawdown_percentiles": {
            "p50": round(percentile(max_drawdowns, 50), 6),
            "p95": round(percentile(max_drawdowns, 95), 6),
        },
        "limitations": [
            "iid resampling ignores trade clustering and changing market regimes",
            "results depend on the supplied historical trade PnL sample",
            "simulation is a research estimate, not a forecast or deployment approval",
        ],
    }


def buy_and_hold_baseline(
    candles, initial_balance, fee_rate=0.001, slippage_rate=0.0005
):
    """Long-only buy-and-hold benchmark using first open and final close.

    Fees and slippage are charged on both sides. This is a simple benchmark,
    not a portfolio allocation or tax model.
    """
    balance = _finite_number(initial_balance, "initial_balance")
    fee = _finite_number(fee_rate, "fee_rate")
    slippage = _finite_number(slippage_rate, "slippage_rate")
    if balance <= 0:
        raise ValueError("initial_balance debe ser positivo")
    if not 0 <= fee < 1 or not 0 <= slippage < 1:
        raise ValueError("fee_rate y slippage_rate deben estar entre 0 y 1")
    values = list(candles)
    if len(values) < 2:
        raise ValueError("Se necesitan al menos dos velas para Buy & Hold")

    def price(candle, key, array_index):
        if isinstance(candle, dict):
            raw = candle.get(key)
        elif isinstance(candle, (list, tuple)) and len(candle) > array_index:
            raw = candle[array_index]
        else:
            raw = None
        result = _finite_number(raw, f"candle.{key}")
        if result <= 0:
            raise ValueError(f"candle.{key} debe ser positivo")
        return result

    entry = price(values[0], "open", 1) * (1 + slippage)
    final_close = price(values[-1], "close", 4)
    exit_price = final_close * (1 - slippage)
    quantity = balance / (entry * (1 + fee))
    entry_fee = quantity * entry * fee
    exit_fee = quantity * exit_price * fee
    gross_pnl = quantity * (exit_price - entry)
    net_pnl = gross_pnl - entry_fee - exit_fee
    final_balance = balance + net_pnl
    return {
        "benchmark": "buy_and_hold_long",
        "initial_balance": round(balance, 6),
        "entry_price_with_slippage": round(entry, 8),
        "exit_price_with_slippage": round(exit_price, 8),
        "quantity": round(quantity, 8),
        "fees": round(entry_fee + exit_fee, 6),
        "net_pnl": round(net_pnl, 6),
        "final_balance": round(final_balance, 6),
        "return_percent": round(net_pnl / balance * 100, 6),
        "assumptions": "first candle open to last candle close; fees and adverse slippage on entry and exit",
    }



def run_walk_forward_backtests(
    raw_candles,
    train_size,
    validation_size,
    test_size,
    step_size=None,
    backtest_kwargs=None,
):
    """Run fixed-strategy backtests on untouched chronological test windows.

    Prior candles are supplied only as indicator warm-up. Trading starts from
    the candle immediately before each test window's first candle (signal
    close), with entries no earlier than the test window. Each fold starts with
    a fresh virtual balance; aggregate PnL is therefore additive, not a
    compounded equity curve. Strategy parameters are fixed, not optimized.
    """
    from .backtest_service import BacktestService

    candles = list(raw_candles)
    if step_size is None:
        step_size = test_size
    splits = chronological_walk_forward_splits(
        candles, train_size, validation_size, test_size, step_size
    )
    kwargs = dict(backtest_kwargs or {})
    initial_balance = _finite_number(
        kwargs.get("initial_balance", 10000.0), "initial_balance"
    )
    if initial_balance <= 0:
        raise ValueError("initial_balance debe ser positivo")

    folds = []
    all_trades = []
    for fold_number, split in enumerate(splits, start=1):
        test_start, test_end = split["test_range"]
        # Signal on the final pre-test candle may enter at the first test open.
        signal_start = test_start - 1
        if signal_start < max(
            kwargs.get("slow_period", 21),
            kwargs.get("rsi_period", 14) + 1,
            15,
        ):
            raise ValueError(
                "train_size + validation_size debe dejar suficiente histórico "
                "para calentar los indicadores antes del primer test"
            )

        engine = BacktestService(**kwargs)
        result = engine.run(
            candles,
            start_index=signal_start,
            end_index=test_end - 1,
        )
        fold_trades = result.get("trades", [])
        all_trades.extend(fold_trades)
        folds.append({
            "fold": fold_number,
            "train_range": split["train_range"],
            "validation_range": split["validation_range"],
            "test_range": split["test_range"],
            "test_candles": test_size,
            "trade_count": result["total_trades"],
            "net_pnl": result["net_profit"],
            "return_percent": result["return_percent"],
            "win_rate_percent": result["win_rate_percent"],
            "profit_factor": result["profit_factor"],
            "max_drawdown_percent": result["max_drawdown_percent"],
            "long_net_pnl": result["long_net_pnl"],
            "short_net_pnl": result["short_net_pnl"],
            "fees": result["total_fees"],
        })

    trade_count = len(all_trades)
    winners = [trade for trade in all_trades if trade["net_pnl"] > 0]
    losers = [trade for trade in all_trades if trade["net_pnl"] < 0]
    gross_profit = sum(trade["net_pnl"] for trade in winners)
    gross_loss = abs(sum(trade["net_pnl"] for trade in losers))
    total_net_pnl = sum(trade["net_pnl"] for trade in all_trades)
    total_fees = sum(fold["fees"] for fold in folds)
    strategy_return = total_net_pnl / (initial_balance * len(folds)) * 100

    benchmark_returns = []
    for fold in folds:
        start, end = fold["test_range"]
        benchmark = buy_and_hold_baseline(
            candles[start:end],
            initial_balance,
            fee_rate=kwargs.get("fee_rate", 0.001),
            slippage_rate=kwargs.get("slippage_rate", 0.0005),
        )
        benchmark_returns.append(benchmark["return_percent"])

    average_benchmark_return = (
        sum(benchmark_returns) / len(benchmark_returns)
        if benchmark_returns else 0.0
    )
    return {
        "framework": "fixed_parameter_chronological_walk_forward",
        "mode": "paper",
        "parameter_optimization_performed": False,
        "fold_count": len(folds),
        "initial_balance_per_fold": round(initial_balance, 6),
        "aggregation": "sum_of_independent_fold_pnl; not compounded",
        "total_trades": trade_count,
        "net_pnl": round(total_net_pnl, 6),
        "average_trade_expectancy": round(total_net_pnl / trade_count, 6)
        if trade_count else None,
        "win_rate_percent": round(len(winners) / trade_count * 100, 4)
        if trade_count else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 6)
        if gross_loss > 0 else None,
        "max_fold_drawdown_percent": round(
            max((fold["max_drawdown_percent"] for fold in folds), default=0.0), 6
        ),
        "total_fees": round(total_fees, 6),
        "average_test_return_percent": round(strategy_return, 6),
        "average_buy_and_hold_return_percent": round(
            average_benchmark_return, 6
        ),
        "excess_return_vs_buy_and_hold_percent": round(
            strategy_return - average_benchmark_return, 6
        ),
        "long_net_pnl": round(sum(
            fold["long_net_pnl"] for fold in folds
        ), 6),
        "short_net_pnl": round(sum(
            fold["short_net_pnl"] for fold in folds
        ), 6),
        "folds": folds,
        "limitations": [
            "strategy parameters remain fixed; no train/validation optimization is performed",
            "each fold starts with independent virtual capital; aggregate return is not compounded",
            "OHLC execution and intrabar ordering remain simplified paper assumptions",
            "walk-forward results do not authorize live trading",
        ],
    }
