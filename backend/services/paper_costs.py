"""Shared adverse-fill and fee assumptions for internal PAPER valuation/execution."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP

PAPER_FEE_RATE = Decimal("0.001")
PAPER_SLIPPAGE_RATE = Decimal("0.0005")
PAPER_PRICE_QUANTUM = Decimal("0.00000001")


def adverse_exit_fill(
    quote_price: Decimal | str | int,
    side: str,
    *,
    slippage_rate: Decimal | str = PAPER_SLIPPAGE_RATE,
) -> Decimal:
    """Return the side-aware adverse simulated exit fill at a public quote."""
    try:
        price = Decimal(str(quote_price))
        slippage = Decimal(str(slippage_rate))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Precio o slippage de salida inválido") from None
    if not price.is_finite() or price <= 0:
        raise ValueError("El precio de salida debe ser positivo y finito")
    if not slippage.is_finite() or slippage < 0 or slippage >= 1:
        raise ValueError("El slippage debe estar entre 0 y 1")

    normalized_side = side.strip().upper() if isinstance(side, str) else ""
    if normalized_side == "LONG":
        raw_fill = price * (Decimal("1") - slippage)
        rounding = ROUND_DOWN
    elif normalized_side == "SHORT":
        raw_fill = price * (Decimal("1") + slippage)
        rounding = ROUND_UP
    else:
        raise ValueError("side debe ser LONG o SHORT")

    fill = raw_fill.quantize(PAPER_PRICE_QUANTUM, rounding=rounding)
    if not fill.is_finite() or fill <= 0:
        raise ValueError("El fill de salida debe ser positivo y finito")
    return fill


def calculate_exit_fee(
    quantity: Decimal | str | int,
    fill_price: Decimal | str | int,
    *,
    minimum_fee: Decimal | str = Decimal("0"),
    fee_rate: Decimal | str = PAPER_FEE_RATE,
) -> Decimal:
    """Return the engine fee floor or a larger persisted/requested minimum."""
    try:
        qty = Decimal(str(quantity))
        price = Decimal(str(fill_price))
        minimum = Decimal(str(minimum_fee))
        rate = Decimal(str(fee_rate))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Cantidad, precio o comisión de salida inválidos") from None
    if not qty.is_finite() or qty <= 0:
        raise ValueError("La cantidad de salida debe ser positiva y finita")
    if not price.is_finite() or price <= 0:
        raise ValueError("El precio de salida debe ser positivo y finito")
    if not minimum.is_finite() or minimum < 0:
        raise ValueError("La comisión mínima debe ser no negativa y finita")
    if not rate.is_finite() or rate < 0:
        raise ValueError("La tasa de comisión debe ser no negativa y finita")
    return max(minimum, qty * price * rate).quantize(
        PAPER_PRICE_QUANTUM,
        rounding=ROUND_UP,
    )
