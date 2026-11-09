
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
                "risk_reward": self.risk_reward,
                "reasons": ["ATR no válido: riesgo no calculable"],
                "mode": "paper"
            }

        long_score = 0
        short_score = 0
        long_reasons = []
        short_reasons = []

        # 1. Cruce/tendencia de medias rápidas y lentas
        if ema_fast > ema_slow:
            long_score += 20
            long_reasons.append("EMA rápida por encima de EMA lenta")
        elif ema_fast < ema_slow:
            short_score += 20
            short_reasons.append("EMA rápida por debajo de EMA lenta")

        # 2. Tendencia general
        if price > ema_trend:
            long_score += 20
            long_reasons.append("Precio por encima de EMA de tendencia")
        elif price < ema_trend:
            short_score += 20
            short_reasons.append("Precio por debajo de EMA de tendencia")

        # 3. RSI
        if 50 < rsi < 70:
            long_score += 15
            long_reasons.append(f"RSI favorable para LONG: {rsi:.1f}")
        elif 30 < rsi < 50:
            short_score += 15
            short_reasons.append(f"RSI favorable para SHORT: {rsi:.1f}")
        elif rsi >= 70:
            long_reasons.append("RSI elevado: posible sobrecompra")
        elif rsi <= 30:
            short_reasons.append("RSI bajo: posible sobreventa")

        # 4. MACD
        histogram = float(macd["histogram"])
        if histogram > 0:
            long_score += 15
            long_reasons.append("Histograma MACD positivo")
        elif histogram < 0:
            short_score += 15
            short_reasons.append("Histograma MACD negativo")

        # 5. VWAP
        vwap_available = vwap is not None and float(vwap) > 0
        if vwap_available:
            if price > vwap:
                long_score += 15
                long_reasons.append("Precio por encima de VWAP")
            elif price < vwap:
                short_score += 15
                short_reasons.append("Precio por debajo de VWAP")

        # 6. Estructura reciente: máximos y mínimos
        recent = candles[-6:]
        highs = [float(c["high"]) for c in recent]
        lows = [float(c["low"]) for c in recent]

        if len(recent) >= 4:
            if highs[-1] > max(highs[:-1]) and lows[-1] > min(lows[:-1]):
                long_score += 15
                long_reasons.append("Estructura reciente favorable al alza")
            elif highs[-1] < max(highs[:-1]) and lows[-1] < min(lows[:-1]):
                short_score += 15
                short_reasons.append("Estructura reciente favorable a la baja")

        # Seleccionar señal
        if long_score >= self.min_score and long_score > short_score:
            signal = "LONG"
            score = long_score
            reasons = long_reasons
            stop_loss = price - atr * self.atr_stop_multiplier
            risk = price - stop_loss
            tp1 = price + risk
            tp2 = price + risk * self.risk_reward
        elif short_score >= self.min_score and short_score > long_score:
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
            reasons = ["No hay suficiente confirmación técnica"]
            stop_loss = None
            tp1 = None
            tp2 = None

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
            "risk_reward": self.risk_reward,
            "long_score": long_score,
            "short_score": short_score,
            "reasons": reasons,
            "mode": "paper"
        }
