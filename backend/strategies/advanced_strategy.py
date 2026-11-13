
class AdvancedStrategy:
    """
    Estrategia técnica avanzada para PAPER TRADING.
    El score es una puntuación de reglas, no una probabilidad
    estadística de ganar.
    """

    def __init__(
        self,
        min_score=60,
        atr_stop_multiplier=1.5,
        risk_reward=2.0
    ):
        self.min_score = min_score
        self.atr_stop_multiplier = atr_stop_multiplier
        self.risk_reward = risk_reward

    def evaluate(
        self,
        candles,
        ema_fast,
        ema_slow,
        ema_trend,
        rsi,
        macd,
        vwap,
        atr
    ):
        if not candles:
            raise ValueError("No hay velas para analizar")

        last = candles[-1]
        price = float(last["close"])

        if atr <= 0:
            return {
                "signal": "NEUTRAL",
                "score": 0,
                "confidence": 0,
                "entry": price,
                "stop_loss": None,
                "take_profit_1": None,
                "take_profit_2": None,
                "invalidation": None,
                "risk_reward": self.risk_reward,
                "long_score": 0,
                "short_score": 0,
                "category_scores": {
                    "trend": {"long": 0, "short": 0, "max": 40},
                    "momentum": {"long": 0, "short": 0, "max": 30},
                    "volume": {"long": 0, "short": 0, "max": 15},
                    "structure": {"long": 0, "short": 0, "max": 15},
                },
                "category_confirmations": {
                    "long": {"trend": False, "momentum": False, "volume": False},
                    "short": {"trend": False, "momentum": False, "volume": False},
                },
                "reasons": ["ATR no válido: riesgo no calculable"],
                "mode": "paper"
            }

        long_score = 0
        short_score = 0
        long_reasons = []
        short_reasons = []
        long_categories = {"trend": False, "momentum": False, "volume": False}
        short_categories = {"trend": False, "momentum": False, "volume": False}
        category_scores = {
            "trend": {"long": 0, "short": 0, "max": 40},
            "momentum": {"long": 0, "short": 0, "max": 30},
            "volume": {"long": 0, "short": 0, "max": 15},
            "structure": {"long": 0, "short": 0, "max": 15},
        }

        # 1. Trend category: EMA relationship and position vs trend EMA.
        if ema_fast > ema_slow:
            long_score += 20
            category_scores["trend"]["long"] += 20
            long_categories["trend"] = True
            long_reasons.append("EMA rápida por encima de EMA lenta")
        elif ema_fast < ema_slow:
            short_score += 20
            category_scores["trend"]["short"] += 20
            short_categories["trend"] = True
            short_reasons.append("EMA rápida por debajo de EMA lenta")

        if price > ema_trend:
            long_score += 20
            category_scores["trend"]["long"] += 20
            long_categories["trend"] = True
            long_reasons.append("Precio por encima de EMA de tendencia")
        elif price < ema_trend:
            short_score += 20
            category_scores["trend"]["short"] += 20
            short_categories["trend"] = True
            short_reasons.append("Precio por debajo de EMA de tendencia")

        # 2. Momentum category: at least RSI or MACD must confirm direction.
        if 50 < rsi < 70:
            long_score += 15
            category_scores["momentum"]["long"] += 15
            long_categories["momentum"] = True
            long_reasons.append(f"RSI favorable para LONG: {rsi:.1f}")
        elif 30 < rsi < 50:
            short_score += 15
            category_scores["momentum"]["short"] += 15
            short_categories["momentum"] = True
            short_reasons.append(f"RSI favorable para SHORT: {rsi:.1f}")
        elif rsi >= 70:
            long_reasons.append("RSI elevado: posible sobrecompra")
        elif rsi <= 30:
            short_reasons.append("RSI bajo: posible sobreventa")

        histogram = float(macd["histogram"])
        if histogram > 0:
            long_score += 15
            category_scores["momentum"]["long"] += 15
            long_categories["momentum"] = True
            long_reasons.append("Histograma MACD positivo")
        elif histogram < 0:
            short_score += 15
            category_scores["momentum"]["short"] += 15
            short_categories["momentum"] = True
            short_reasons.append("Histograma MACD negativo")

        # 3. Volume category: VWAP must be available and agree with direction.
        vwap_available = vwap is not None and float(vwap) > 0
        if vwap_available:
            if price > vwap:
                long_score += 15
                category_scores["volume"]["long"] += 15
                long_categories["volume"] = True
                long_reasons.append("Precio por encima de VWAP UTC")
            elif price < vwap:
                short_score += 15
                category_scores["volume"]["short"] += 15
                short_categories["volume"] = True
                short_reasons.append("Precio por debajo de VWAP UTC")

        # 4. Price structure adds score but cannot replace a missing category.
        recent = candles[-6:]
        highs = [float(c["high"]) for c in recent]
        lows = [float(c["low"]) for c in recent]
        if len(recent) >= 4:
            if highs[-1] > max(highs[:-1]) and lows[-1] > min(lows[:-1]):
                long_score += 15
                category_scores["structure"]["long"] += 15
                long_reasons.append("Estructura reciente favorable al alza")
            elif highs[-1] < max(highs[:-1]) and lows[-1] < min(lows[:-1]):
                short_score += 15
                category_scores["structure"]["short"] += 15
                short_reasons.append("Estructura reciente favorable a la baja")

        long_confirmed = all(long_categories.values())
        short_confirmed = all(short_categories.values())
        if not vwap_available:
            long_reasons.append("VWAP no disponible: falta confirmación de volumen")
            short_reasons.append("VWAP no disponible: falta confirmación de volumen")

        # Seleccionar señal
        if long_confirmed and long_score >= self.min_score and long_score > short_score:
            signal = "LONG"
            score = long_score
            reasons = long_reasons
            stop_loss = price - atr * self.atr_stop_multiplier
            risk = price - stop_loss
            tp1 = price + risk
            tp2 = price + risk * self.risk_reward
        elif short_confirmed and short_score >= self.min_score and short_score > long_score:
            signal = "SHORT"
            score = short_score
            reasons = short_reasons
            stop_loss = price + atr * self.atr_stop_multiplier
            risk = stop_loss - price
            tp1 = price - risk
            tp2 = price - risk * self.risk_reward
        else:
            signal = "NEUTRAL"
            score = max(long_score, short_score)
            missing = []
            if not long_confirmed and not short_confirmed:
                missing = [
                    category for category in ("trend", "momentum", "volume")
                    if not long_categories[category] and not short_categories[category]
                ]
            reasons = ["No hay suficiente confirmación técnica"]
            if missing:
                reasons.append("Faltan categorías de confirmación: " + ", ".join(missing))
            stop_loss = None
            tp1 = None
            tp2 = None

        invalidation = None
        if stop_loss is not None:
            invalidation = {
                "price": round(stop_loss, 6),
                "trigger": "at_or_below" if signal == "LONG" else "at_or_above",
                "basis": "atr_stop",
            }

        if not vwap_available:
            reasons.append("VWAP no disponible: volumen total cero o dato ausente")

        return {
            "signal": signal,
            "score": score,
            "confidence": score,
            "entry": round(price, 6),
            "stop_loss": round(stop_loss, 6) if stop_loss is not None else None,
            "take_profit_1": round(tp1, 6) if tp1 is not None else None,
            "take_profit_2": round(tp2, 6) if tp2 is not None else None,
            "invalidation": invalidation,
            "risk_reward": self.risk_reward,
            "long_score": long_score,
            "short_score": short_score,
            "category_scores": category_scores,
            "category_confirmations": {
                "long": long_categories,
                "short": short_categories,
            },
            "reasons": reasons,
            "mode": "paper"
        }
