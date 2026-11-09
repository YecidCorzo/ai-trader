def validate_signal_history(closes, minimum):
    """Require enough completed closes for every requested indicator."""
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        raise ValueError("El mínimo de velas debe ser un entero positivo")
    if len(closes) < minimum:
        raise ValueError(
            f"Insufficient closed candle data: {len(closes)} available, "
            f"{minimum} required"
        )
    return True
