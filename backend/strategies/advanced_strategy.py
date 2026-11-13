import math


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
        risk_reward=2.0,
        min_atr_percent=0.001,
        max_atr_percent=0.05,
        min_ema_slope_percent=0.0001,
        min_volume_ratio=1.0,
        volume_mean_period=20,
    ):
        self.min_score = min_score
        self.atr_stop_multiplier = atr_stop_multiplier
        self.risk_reward = risk_reward
        self.min_atr_percent = min_atr_percent
        self.max_atr_percent = max_atr_percent
        self.min_ema_slope_percent = min_ema_slope_percent
        self.min_volume_ratio = min_volume_ratio
        self.volume_mean_period = volume_mean_period
        numeric_settings = (
            self.min_atr_percent, self.max_atr_percent,
            self.min_ema_slope_percent, self.min_volume_ratio,
        )
        if not all(math.isfinite(float(value)) for value in numeric_settings):
            raise ValueError("Los filtros de régimen deben ser valores finitos")
        if self.min_atr_percent < 0 or self.max_atr_percent <= self.min_atr_percent:
            raise ValueError("La banda ATR% debe ser positiva y creciente")
        if self.min_ema_slope_percent < 0 or self.min_volume_ratio <= 0:
            raise ValueError("Los umbrales de pendiente y volumen deben ser positivos")
        if (
            not isinstance(self.volume_mean_period, int)
            or isinstance(self.volume_mean_period, bool)
            or self.volume_mean_period < 1
        ):
            raise ValueError("volume_mean_period debe ser un entero positivo")

    def evaluate(
        self,
        candles,
        ema_fast,
        ema_slow,
        ema_trend,
        rsi,
        macd,
        vwap,
        atr,
        ema_trend_slope=None,
    ):
        if not candles:
            raise ValueError("No hay velas para analizar")

        last = candles[-1]
        price = float(last["close"])

        atr_percent = atr / price if price > 0 and atr > 0 else None
        atr_band_ok = (
            atr_percent is not None
            and self.min_atr_percent <= atr_percent <= self.max_atr_percent
        )
        slope_available = (
            ema_trend_slope is not None
            and isinstance(ema_trend_slope, (int, float))
            and math.isfinite(float(ema_trend_slope))
        )
        slope_value = float(ema_trend_slope) if slope_available else None
        long_slope_ok = slope_available and slope_value > self.min_ema_slope_percent
        short_slope_ok = slope_available and slope_value < -self.min_ema_slope_percent

        recent_volumes = [
            float(candle.get("volume", 0))
            for candle in candles[-self.volume_mean_period:]
        ]
        volume_mean = (
            sum(recent_volumes) / self.volume_mean_period
            if len(recent_volumes) == self.volume_mean_period
            else None
        )
        current_volume = float(last.get("volume", 0))
        volume_ratio = current_volume / volume_mean if volume_mean and volume_mean > 0 else None
        volume_regime_ok = volume_ratio is not None and volume_ratio >= self.min_volume_ratio

        regime_filters = {
            "atr_percent": round(atr_percent, 8) if atr_percent is not None else None,
            "min_atr_percent": self.min_atr_percent,
            "max_atr_percent": self.max_atr_percent,
            "atr_ok": bool(atr_band_ok),
            "ema_trend_slope_percent": round(slope_value, 8) if slope_available else None,
            "min_ema_slope_percent": self.min_ema_slope_percent,
            "long_ema_slope_ok": bool(long_slope_ok),
            "short_ema_slope_ok": bool(short_slope_ok),
            "volume_mean_period": self.volume_mean_period,
            "current_volume": current_volume,
            "volume_mean": round(volume_mean, 8) if volume_mean is not None else None,
            "volume_ratio": round(volume_ratio, 8) if volume_ratio is not None else None,
            "min_volume_ratio": self.min_volume_ratio,
            "volume_ok": bool(volume_regime_ok),
        }

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
                "regime_filters": regime_filters,
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
        regime_long_ok = atr_band_ok and long_slope_ok and volume_regime_ok
        regime_short_ok = atr_band_ok and short_slope_ok and volume_regime_ok
        regime_filters["long_ok"] = bool(regime_long_ok)
        regime_filters["short_ok"] = bool(regime_short_ok)
        if not vwap_available:
            long_reasons.append("VWAP no disponible: falta confirmación de volumen")
            short_reasons.append("VWAP no disponible: falta confirmación de volumen")

        # Seleccionar señal
        if long_confirmed and regime_long_ok and long_score >= self.min_score and long_score > short_score:
            signal = "LONG"
            score = long_score
            reasons = long_reasons
            stop_loss = price - atr * self.atr_stop_multiplier
            risk = price - stop_loss
            tp1 = price + risk
            tp2 = price + risk * self.risk_reward
        elif short_confirmed and regime_short_ok and short_score >= self.min_score and short_score > long_score:
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
            regime_blocks = []
            if not atr_band_ok:
                regime_blocks.append("ATR% fuera de banda")
            if not volume_regime_ok:
                regime_blocks.append("volumen inferior a la media de 20 velas o no disponible")
            if not long_slope_ok and not short_slope_ok:
                regime_blocks.append("pendiente EMA50 insuficiente o no disponible")
            if regime_blocks:
                reasons.append("Filtros de régimen bloquean señal: " + "; ".join(regime_blocks))
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
            "regime_filters": regime_filters,
            "category_confirmations": {
                "long": long_categories,
                "short": short_categories,
            },
            "reasons": reasons,
            "mode": "paper"
        }
