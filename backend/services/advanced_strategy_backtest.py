"""Historical simulation using the exact AdvancedStrategy signal contract."""
from __future__ import annotations

import math

from backend.strategies.advanced_strategy import AdvancedStrategy
from backend.services.backtest_service import BacktestService


class AdvancedStrategyBacktestService:
    """Backtest AdvancedStrategy signals without looking beyond each closed bar."""

    def __init__(
        self, *, initial_balance=10000.0, fee_rate=0.001,
        slippage_rate=0.0005, risk_per_trade=0.01, strategy=None,
    ):
        self.initial_balance = float(initial_balance)
        self.fee_rate = float(fee_rate)
        self.slippage_rate = float(slippage_rate)
        self.risk_per_trade = float(risk_per_trade)
        self.strategy = strategy or AdvancedStrategy()
        values = (self.initial_balance, self.fee_rate, self.slippage_rate, self.risk_per_trade)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Los parámetros deben ser valores finitos")
        if self.initial_balance <= 0:
            raise ValueError("El capital inicial debe ser positivo")
        if not 0 <= self.fee_rate < 1 or not 0 <= self.slippage_rate < 1:
            raise ValueError("Comisión y slippage deben estar entre 0 y 1")
        if not 0 < self.risk_per_trade <= 0.01:
            raise ValueError("El riesgo por operación debe estar entre 0 y 1 %")

    @staticmethod
    def _ema_series(values, period):
        multiplier = 2.0 / (period + 1)
        result = []
        for value in values:
            value = float(value)
            result.append(value if not result else (value - result[-1]) * multiplier + result[-1])
        return result

    @staticmethod
    def _atr_series(candles, period=14):
        result = [None] * len(candles)
        ranges = []
        for index, candle in enumerate(candles):
            if index == 0:
                true_range = candle["high"] - candle["low"]
            else:
                previous = candles[index - 1]["close"]
                true_range = max(
                    candle["high"] - candle["low"],
                    abs(candle["high"] - previous),
                    abs(candle["low"] - previous),
                )
            ranges.append(true_range)
            if index >= period:
                result[index] = sum(ranges[index - period + 1:index + 1]) / period
        return result

    @classmethod
    def _indicator_series(cls, candles):
        closes = [item["close"] for item in candles]
        ema_fast = cls._ema_series(closes, 9)
        ema_slow = cls._ema_series(closes, 21)
        ema_trend = cls._ema_series(closes, 50)
        from backend.indicators.rsi import calculate_rsi_series
        rsi = calculate_rsi_series(closes, 14)

        macd_fast = cls._ema_series(closes, 12)
        macd_slow = cls._ema_series(closes, 26)
        macd_line = [fast - slow for fast, slow in zip(macd_fast, macd_slow)]
        macd_signal = cls._ema_series(macd_line, 9)
        macd_histogram = [line - signal for line, signal in zip(macd_line, macd_signal)]

        vwap = []
        cumulative_pv = 0.0
        cumulative_volume = 0.0
        for candle in candles:
            volume = candle["volume"]
            typical = (candle["high"] + candle["low"] + candle["close"]) / 3.0
            cumulative_pv += typical * volume
            cumulative_volume += volume
            vwap.append(cumulative_pv / cumulative_volume if cumulative_volume > 0 else None)

        return {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "ema_trend": ema_trend,
            "rsi": rsi,
            "macd_histogram": macd_histogram,
            "vwap": vwap,
            "atr": cls._atr_series(candles, 14),
        }

    @staticmethod
    def _normalize_candles(raw_candles):
        candles = []
        for row in raw_candles:
            try:
                if isinstance(row, dict):
                    candle = {
                        "time": row.get("time", row.get("timestamp")),
                        "open": float(row["open"]), "high": float(row["high"]),
                        "low": float(row["low"]), "close": float(row["close"]),
                        "volume": float(row.get("volume", 0)),
                    }
                else:
                    if len(row) < 6:
                        raise ValueError("La vela debe contener al menos 6 campos")
                    candle = {
                        "time": row[0], "open": float(row[1]), "high": float(row[2]),
                        "low": float(row[3]), "close": float(row[4]), "volume": float(row[5]),
                    }
            except (KeyError, TypeError, IndexError) as error:
                raise ValueError("Formato de vela inválido o incompleto") from error
            prices = [candle[key] for key in ("open", "high", "low", "close", "volume")]
            if candle["time"] is None or not all(math.isfinite(value) for value in prices):
                raise ValueError("La vela contiene timestamp o valores no finitos")
            if any(candle[key] <= 0 for key in ("open", "high", "low", "close")) or candle["volume"] < 0:
                raise ValueError("La vela contiene precios o volumen inválidos")
            if candle["high"] < max(candle["open"], candle["close"], candle["low"]):
                raise ValueError("La vela contiene valores OHLC inconsistentes")
            if candle["low"] > min(candle["open"], candle["close"], candle["high"]):
                raise ValueError("La vela contiene valores OHLC inconsistentes")
            candles.append(candle)
        try:
            if any(candles[i]["time"] >= candles[i + 1]["time"] for i in range(len(candles) - 1)):
                raise ValueError("Las velas deben estar ordenadas cronológicamente y sin duplicados")
        except TypeError as error:
            raise ValueError("Los timestamps deben usar un formato consistente") from error
        return candles

    def run(self, raw_candles, *, start_index=50, end_index=None):
        candles = self._normalize_candles(raw_candles)
        if len(candles) < 52:
            raise ValueError("Se necesitan al menos 52 velas para backtest AdvancedStrategy")
        end_index = len(candles) - 1 if end_index is None else end_index
        if (
            not isinstance(start_index, int) or isinstance(start_index, bool)
            or not isinstance(end_index, int) or isinstance(end_index, bool)
            or start_index < 50 or end_index >= len(candles) or end_index <= start_index
        ):
            raise ValueError("Ventana de backtest AdvancedStrategy inválida")

        indicators = self._indicator_series(candles)
        balance = self.initial_balance
        peak_equity = balance
        max_drawdown = 0.0
        trades = []
        skipped_signals = 0
        index = start_index

        while index < min(end_index, len(candles) - 1):
            atr = indicators["atr"][index]
            rsi = indicators["rsi"][index]
            if atr is None or atr <= 0 or rsi is None:
                index += 1
                continue
            signal = self.strategy.evaluate(
                candles=candles[:index + 1],
                ema_fast=indicators["ema_fast"][index],
                ema_slow=indicators["ema_slow"][index],
                ema_trend=indicators["ema_trend"][index],
                rsi=rsi,
                macd={"histogram": indicators["macd_histogram"][index]},
                vwap=indicators["vwap"][index],
                atr=atr,
            )
            direction = signal.get("signal")
            if direction not in {"LONG", "SHORT"}:
                index += 1
                continue

            entry_index = index + 1
            next_candle = candles[entry_index]
            raw_entry = next_candle["open"]
            entry = raw_entry * (1 + self.slippage_rate if direction == "LONG" else 1 - self.slippage_rate)
            stop = float(signal["stop_loss"])
            target_1 = float(signal["take_profit_1"])
            target_2 = float(signal["take_profit_2"])
            if (
                not all(math.isfinite(value) and value > 0 for value in (entry, stop, target_1, target_2))
                or (direction == "LONG" and not stop < entry < target_1 < target_2)
                or (direction == "SHORT" and not target_2 < target_1 < entry < stop)
            ):
                skipped_signals += 1
                index += 1
                continue

            stop_fill = stop * (1 - self.slippage_rate if direction == "LONG" else 1 + self.slippage_rate)
            unit_loss = abs(entry - stop_fill) + entry * self.fee_rate + stop_fill * self.fee_rate
            if not math.isfinite(unit_loss) or unit_loss <= 0 or balance <= 0:
                skipped_signals += 1
                index += 1
                continue
            risk_budget = balance * self.risk_per_trade
            quantity = min(
                risk_budget / unit_loss,
                balance / (entry * (1 + self.fee_rate)),
            )
            quantity = math.floor(quantity * 100_000_000) / 100_000_000
            if not math.isfinite(quantity) or quantity <= 0:
                skipped_signals += 1
                index += 1
                continue

            entry_fee = quantity * entry * self.fee_rate
            liquidation = (
                BacktestService._short_liquidation_price(entry, self.fee_rate, 0.25)
                if direction == "SHORT" else None
            )
            exit_price = None
            exit_reason = None
            exit_index = None
            for candle_index in range(entry_index, end_index + 1):
                candle = candles[candle_index]
                exit_price, exit_reason = BacktestService._resolve_candle_exit(
                    direction, candle, stop, target_2, self.slippage_rate, liquidation,
                )
                mark_price = exit_price if exit_reason else (
                    candle["low"] if direction == "LONG" else candle["high"]
                )
                unrealized = quantity * (
                    mark_price - entry if direction == "LONG" else entry - mark_price
                )
                estimated_exit_fee = quantity * mark_price * self.fee_rate
                equity = balance + unrealized - entry_fee - estimated_exit_fee
                peak_equity = max(peak_equity, equity)
                if peak_equity > 0:
                    max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)
                if exit_reason:
                    exit_index = candle_index
                    break

            if exit_price is None:
                exit_index = end_index
                close = candles[end_index]["close"]
                exit_price = close * (1 - self.slippage_rate if direction == "LONG" else 1 + self.slippage_rate)
                exit_reason = "end_of_data"

            gross_pnl = quantity * (
                exit_price - entry if direction == "LONG" else entry - exit_price
            )
            exit_fee = quantity * exit_price * self.fee_rate
            net_pnl = gross_pnl - entry_fee - exit_fee
            balance += net_pnl
            peak_equity = max(peak_equity, balance)
            if peak_equity > 0:
                max_drawdown = max(max_drawdown, (peak_equity - balance) / peak_equity)
            trades.append({
                "direction": direction,
                "score": signal.get("score"),
                "reasons": signal.get("reasons", []),
                "signal_time": candles[index]["time"],
                "entry_time": candles[entry_index]["time"],
                "exit_time": candles[exit_index]["time"],
                "entry": round(entry, 8),
                "exit": round(exit_price, 8),
                "stop_loss": round(stop, 8),
                "take_profit_1": round(target_1, 8),
                "take_profit_2": round(target_2, 8),
                "quantity": round(quantity, 8),
                "entry_fee": round(entry_fee, 8),
                "exit_fee": round(exit_fee, 8),
                "gross_pnl": round(gross_pnl, 8),
                "net_pnl": round(net_pnl, 8),
                "balance": round(balance, 8),
                "exit_reason": exit_reason,
            })
            index = exit_index + 1

        winners = [trade for trade in trades if trade["net_pnl"] > 0]
        losers = [trade for trade in trades if trade["net_pnl"] < 0]
        gross_profit = sum(trade["net_pnl"] for trade in winners)
        gross_loss = abs(sum(trade["net_pnl"] for trade in losers))
        total_pnl = balance - self.initial_balance
        return {
            "mode": "paper",
            "strategy": "AdvancedStrategy",
            "initial_balance": round(self.initial_balance, 2),
            "final_balance": round(balance, 2),
            "net_profit": round(total_pnl, 2),
            "return_percent": round(total_pnl / self.initial_balance * 100, 2),
            "total_trades": len(trades),
            "skipped_signals": skipped_signals,
            "expectancy_per_trade": round(total_pnl / len(trades), 4) if trades else None,
            "win_rate_percent": round(len(winners) / len(trades) * 100, 2) if trades else 0.0,
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
            "max_drawdown_percent": round(max_drawdown * 100, 2),
            "fee_rate": self.fee_rate,
            "slippage_rate": self.slippage_rate,
            "risk_per_trade": self.risk_per_trade,
            "take_profit_model": "full_exit_at_tp2_no_partial_tp1",
            "trades": trades,
        }
