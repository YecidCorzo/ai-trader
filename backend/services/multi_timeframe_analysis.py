"""Multi-timeframe market analysis using the shared AdvancedStrategy rules."""
from __future__ import annotations

import math

try:
    from backend.indicators.ema import calculate_ema_series
    from backend.indicators.rsi import calculate_rsi
    from backend.indicators.macd import calculate_macd
    from backend.indicators.vwap import calculate_vwap
    from backend.indicators.atr import calculate_atr
    from backend.strategies.advanced_strategy import AdvancedStrategy
except ImportError:
    from indicators.ema import calculate_ema_series
    from indicators.rsi import calculate_rsi
    from indicators.macd import calculate_macd
    from indicators.vwap import calculate_vwap
    from indicators.atr import calculate_atr
    from strategies.advanced_strategy import AdvancedStrategy


class MultiTimeframeAnalysisService:
    """Analyze closed 5m/15m/1h candles and require directional consensus."""

    DEFAULT_INTERVALS = ("5m", "15m", "1h")

    def __init__(self, market_service, *, strategy_factory=None, limit=500):
        self.market_service = market_service
        self.strategy_factory = strategy_factory or AdvancedStrategy
        self.limit = limit
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 52:
            raise ValueError("limit debe ser un entero >= 52")

    @staticmethod
    def _normalize_rows(rows):
        candles = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                raise ValueError("Formato de vela incompleto")
            try:
                candle = {
                    "time": int(float(row[0]) / 1000),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError("Vela contiene datos inválidos") from error
            values = [candle[key] for key in ("open", "high", "low", "close", "volume")]
            if (
                candle["time"] <= 0
                or not all(math.isfinite(value) for value in values)
                or min(candle["open"], candle["high"], candle["low"], candle["close"]) <= 0
                or candle["volume"] < 0
                or candle["high"] < max(candle["open"], candle["close"], candle["low"])
                or candle["low"] > min(candle["open"], candle["close"], candle["high"])
            ):
                raise ValueError("Vela contiene OHLCV inválidos")
            candles.append(candle)
        if any(candles[i]["time"] >= candles[i + 1]["time"] for i in range(len(candles) - 1)):
            raise ValueError("Velas deben estar ordenadas y no duplicadas")
        return candles

    def _analyze_interval(self, interval):
        try:
            raw = self.market_service.get_candles(
                interval=interval, limit=self.limit, closed_only=True,
            )
            if len(raw) < 52:
                return {
                    "interval": interval,
                    "available": False,
                    "signal": "NEUTRAL",
                    "reason": "insufficient_closed_history",
                    "candles_received": len(raw),
                }
            candles = self._normalize_rows(raw)
            closes = [candle["close"] for candle in candles]
            ema_fast_series = calculate_ema_series(closes, 9)
            ema_slow_series = calculate_ema_series(closes, 21)
            ema_trend_series = calculate_ema_series(closes, 50)
            previous_trend = ema_trend_series[-6]
            ema_trend_slope = (
                (ema_trend_series[-1] - previous_trend) / previous_trend
                if previous_trend else None
            )
            rsi = calculate_rsi(closes, period=14)
            macd = calculate_macd(closes)
            vwap = calculate_vwap(candles)
            atr = calculate_atr(candles, period=14)
            result = self.strategy_factory().evaluate(
                candles=candles,
                ema_fast=ema_fast_series[-1],
                ema_slow=ema_slow_series[-1],
                ema_trend=ema_trend_series[-1],
                ema_trend_slope=ema_trend_slope,
                rsi=rsi,
                macd=macd,
                vwap=vwap,
                atr=atr,
            )
            return {
                "interval": interval,
                "available": True,
                "candles_received": len(candles),
                "last_closed_time": candles[-1]["time"],
                "close": closes[-1],
                "indicators": {
                    "ema_9": ema_fast_series[-1],
                    "ema_21": ema_slow_series[-1],
                    "ema_50": ema_trend_series[-1],
                    "ema_50_slope_percent": ema_trend_slope,
                    "rsi_14": rsi,
                    "macd": macd,
                    "vwap_utc_day": vwap,
                    "atr_14": atr,
                },
                "signal": result.get("signal", "NEUTRAL"),
                "score": result.get("score", 0),
                "long_score": result.get("long_score", 0),
                "short_score": result.get("short_score", 0),
                "category_scores": result.get("category_scores"),
                "category_confirmations": result.get("category_confirmations"),
                "regime_filters": result.get("regime_filters"),
                "entry": result.get("entry"),
                "stop_loss": result.get("stop_loss"),
                "take_profit_1": result.get("take_profit_1"),
                "take_profit_2": result.get("take_profit_2"),
                "invalidation": result.get("invalidation"),
                "reasons": result.get("reasons", []),
            }
        except Exception:
            return {
                "interval": interval,
                "available": False,
                "signal": "NEUTRAL",
                "reason": "market_data_or_indicator_error",
            }

    def run(self, *, intervals=None):
        selected = tuple(intervals or self.DEFAULT_INTERVALS)
        if len(selected) < 2 or len(set(selected)) != len(selected):
            raise ValueError("Se requieren al menos dos timeframes distintos")
        results = {interval: self._analyze_interval(interval) for interval in selected}
        signals = [results[interval]["signal"] for interval in selected]
        available = all(results[interval]["available"] for interval in selected)
        consensus = (
            signals[0]
            if available and signals[0] in {"LONG", "SHORT"} and all(
                signal == signals[0] for signal in signals
            )
            else "NEUTRAL"
        )
        if not available:
            reason = "No todos los timeframes tienen histórico cerrado y datos válidos"
        elif consensus == "NEUTRAL":
            reason = "Los timeframes no confirman una misma dirección"
        else:
            reason = f"Consenso {consensus}: todos los timeframes confirman la misma dirección"
        return {
            "symbol": "SOL/USDT",
            "mode": "paper",
            "analysis": "multi_timeframe_advanced_strategy",
            "consensus": consensus,
            "consensus_rule": "all_selected_timeframes_must_agree",
            "reason": reason,
            "timeframes": results,
            "live_trading_authorized": False,
        }
