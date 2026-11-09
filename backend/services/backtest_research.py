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
    if step_size is None:
        step_size = test_size
    _positive_int(step_size, "step_size")

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
