"""Historical simulation using the exact AdvancedStrategy signal contract."""
from __future__ import annotations

import math

try:
    from backend.strategies.advanced_strategy import AdvancedStrategy
    from backend.services.backtest_service import BacktestService
    from backend.indicators.rsi import calculate_rsi_series
    from backend.indicators.macd import calculate_macd
    from backend.indicators.vwap import utc_day_key
    from backend.indicators.atr import calculate_atr
    from backend.indicators.ema import calculate_ema
except ImportError:
    from strategies.advanced_strategy import AdvancedStrategy
    from services.backtest_service import BacktestService
    from indicators.rsi import calculate_rsi_series
    from indicators.macd import calculate_macd
    from indicators.vwap import utc_day_key
    from indicators.atr import calculate_atr
    from indicators.ema import calculate_ema


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
        self.strategy = strategy or AdvancedStrategy(
            fee_rate=self.fee_rate,
            slippage_rate=self.slippage_rate,
        )
        self.cost_stop_activation_r = 1.5
        self.round_trip_cost_rate = 2 * (self.fee_rate + self.slippage_rate)
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
        ema_trend_slope = [None] * len(ema_trend)
        for index in range(5, len(ema_trend)):
            previous = ema_trend[index - 5]
            if previous:
                ema_trend_slope[index] = (ema_trend[index] - previous) / previous
        rsi = calculate_rsi_series(closes, 14)

        macd_fast = cls._ema_series(closes, 12)
        macd_slow = cls._ema_series(closes, 26)
        macd_line = [fast - slow for fast, slow in zip(macd_fast, macd_slow)]
        macd_signal = cls._ema_series(macd_line, 9)
        macd_histogram = [line - signal for line, signal in zip(macd_line, macd_signal)]

        vwap = []
        current_utc_day = None
        cumulative_pv = 0.0
        cumulative_volume = 0.0
        for candle in candles:
            candle_day = utc_day_key(candle["time"])
            if candle_day != current_utc_day:
                current_utc_day = candle_day
                cumulative_pv = 0.0
                cumulative_volume = 0.0
            volume = candle["volume"]
            typical = (candle["high"] + candle["low"] + candle["close"]) / 3.0
            cumulative_pv += typical * volume
            cumulative_volume += volume
            vwap.append(cumulative_pv / cumulative_volume if cumulative_volume > 0 else None)

        return {
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "ema_trend": ema_trend,
            "ema_trend_slope": ema_trend_slope,
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
                candles=candles[max(0, index - 19):index + 1],
                ema_fast=indicators["ema_fast"][index],
                ema_slow=indicators["ema_slow"][index],
                ema_trend=indicators["ema_trend"][index],
                ema_trend_slope=indicators["ema_trend_slope"][index],
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
            signal_entry = float(signal.get("entry", candles[index]["close"]))
            signal_stop = float(signal["stop_loss"])
            risk_distance = abs(signal_entry - signal_stop)
            risk_reward = float(signal.get("risk_reward", 2.0))
            if (
                not all(math.isfinite(value) and value > 0 for value in (entry, signal_entry, signal_stop, risk_distance, risk_reward))
                or risk_distance <= 0 or risk_reward <= 0
            ):
                skipped_signals += 1
                index += 1
                continue
            if direction == "LONG":
                stop = entry - risk_distance
                target_1 = entry + risk_distance
                target_2 = entry + risk_distance * risk_reward
            else:
                stop = entry + risk_distance
                target_1 = entry - risk_distance
                target_2 = entry - risk_distance * risk_reward
            if min(stop, target_1, target_2) <= 0:
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
            if math.floor(quantity * 0.5 * 100_000_000) / 100_000_000 <= 0:
                skipped_signals += 1
                index += 1
                continue

            entry_fee = quantity * entry * self.fee_rate
            liquidation = (
                BacktestService._short_liquidation_price(entry, self.fee_rate, 0.25)
                if direction == "SHORT" else None
            )
            partial_quantity = 0.0
            partial_exit_price = None
            partial_exit_fee = 0.0
            partial_gross_pnl = 0.0
            partial_net_pnl = 0.0
            partial_entry_fee = 0.0
            remaining_quantity = quantity
            remaining_entry_fee = entry_fee
            tp1_hit = False
            tp1_candle_index = None
            cost_stop_active = False
            cost_stop_price = (
                entry * (1 + self.fee_rate) / ((1 - self.fee_rate) * (1 - self.slippage_rate))
                if direction == "LONG"
                else entry * (1 - self.fee_rate) / ((1 + self.fee_rate) * (1 + self.slippage_rate))
            )
            activation_price = (
                entry + risk_distance * self.cost_stop_activation_r
                if direction == "LONG"
                else entry - risk_distance * self.cost_stop_activation_r
            )
            tp2_hit = False
            exit_price = None
            exit_reason = None
            exit_index = None

            for candle_index in range(entry_index, end_index + 1):
                candle = candles[candle_index]
                open_price = candle["open"]

                if not tp1_hit:
                    if direction == "LONG":
                        risk_exit = open_price <= stop or candle["low"] <= stop
                        tp1_touched = candle["high"] >= target_1
                        # If stop and TP1 share one OHLC candle, stop wins.
                        if risk_exit:
                            fill_quote = open_price if open_price <= stop else stop
                            exit_price = fill_quote * (1 - self.slippage_rate)
                            exit_reason = "stop_loss"
                        elif tp1_touched:
                            tp1_hit = True
                            tp1_candle_index = candle_index
                    else:
                        risk_exit_level = min(stop, liquidation) if liquidation is not None else stop
                        risk_exit_reason = (
                            "liquidation"
                            if liquidation is not None and liquidation < stop
                            else "stop_loss"
                        )
                        risk_exit = (
                            open_price >= risk_exit_level
                            or candle["high"] >= risk_exit_level
                        )
                        tp1_touched = candle["low"] <= target_1
                        if risk_exit:
                            fill_quote = open_price if open_price >= risk_exit_level else risk_exit_level
                            exit_price = fill_quote * (1 + self.slippage_rate)
                            exit_reason = risk_exit_reason
                        elif tp1_touched:
                            tp1_hit = True
                            tp1_candle_index = candle_index
                else:
                    if direction == "LONG":
                        if cost_stop_active:
                            if open_price <= cost_stop_price:
                                exit_price = open_price * (1 - self.slippage_rate)
                                exit_reason = "cost_aware_stop"
                            elif candle["low"] <= cost_stop_price:
                                exit_price = cost_stop_price * (1 - self.slippage_rate)
                                exit_reason = "cost_aware_stop"
                            elif candle["high"] >= target_2:
                                exit_price = target_2 * (1 - self.slippage_rate)
                                exit_reason = "take_profit_2"
                                tp2_hit = True
                        else:
                            if open_price <= stop or candle["low"] <= stop:
                                fill_quote = open_price if open_price <= stop else stop
                                exit_price = fill_quote * (1 - self.slippage_rate)
                                exit_reason = "stop_loss_after_tp1"
                            elif candle["high"] >= target_2:
                                exit_price = target_2 * (1 - self.slippage_rate)
                                exit_reason = "take_profit_2"
                                tp2_hit = True
                            elif candle_index > tp1_candle_index and candle["high"] >= activation_price:
                                # Activate the cost-aware stop only after this candle closes.
                                cost_stop_active = True
                    else:
                        if cost_stop_active:
                            if open_price >= cost_stop_price:
                                exit_price = open_price * (1 + self.slippage_rate)
                                exit_reason = "cost_aware_stop"
                            elif candle["high"] >= cost_stop_price:
                                exit_price = cost_stop_price * (1 + self.slippage_rate)
                                exit_reason = "cost_aware_stop"
                            elif candle["low"] <= target_2:
                                exit_price = target_2 * (1 + self.slippage_rate)
                                exit_reason = "take_profit_2"
                                tp2_hit = True
                        else:
                            if open_price >= stop or candle["high"] >= stop:
                                fill_quote = open_price if open_price >= stop else stop
                                exit_price = fill_quote * (1 + self.slippage_rate)
                                exit_reason = "stop_loss_after_tp1"
                            elif candle["low"] <= target_2:
                                exit_price = target_2 * (1 + self.slippage_rate)
                                exit_reason = "take_profit_2"
                                tp2_hit = True
                            elif candle_index > tp1_candle_index and candle["low"] <= activation_price:
                                # Activate the cost-aware stop only after this candle closes.
                                cost_stop_active = True

                if tp1_hit and partial_quantity == 0.0:
                    partial_quantity = math.floor(quantity * 0.5 * 100_000_000) / 100_000_000
                    remaining_quantity = quantity - partial_quantity
                    partial_exit_price = target_1 * (
                        1 - self.slippage_rate if direction == "LONG" else 1 + self.slippage_rate
                    )
                    partial_entry_fee = entry_fee * (partial_quantity / quantity)
                    partial_exit_fee = partial_quantity * partial_exit_price * self.fee_rate
                    partial_gross_pnl = partial_quantity * (
                        partial_exit_price - entry
                        if direction == "LONG" else entry - partial_exit_price
                    )
                    partial_net_pnl = partial_gross_pnl - partial_entry_fee - partial_exit_fee
                    remaining_entry_fee = entry_fee - partial_entry_fee
                    balance += partial_net_pnl

                    # TP2 can be reached on the TP1 candle. No stop is moved
                    # intrabar; the 1.5R activation is eligible from the next bar.
                    if direction == "LONG" and candle["high"] >= target_2:
                        exit_price = target_2 * (1 - self.slippage_rate)
                        exit_reason = "take_profit_2"
                        tp2_hit = True
                    elif direction == "SHORT" and candle["low"] <= target_2:
                        exit_price = target_2 * (1 + self.slippage_rate)
                        exit_reason = "take_profit_2"
                        tp2_hit = True

                mark_price = exit_price if exit_reason else (
                    candle["low"] if direction == "LONG" else candle["high"]
                )
                unrealized = remaining_quantity * (
                    mark_price - entry if direction == "LONG" else entry - mark_price
                )
                estimated_exit_fee = remaining_quantity * mark_price * self.fee_rate
                equity = balance + unrealized - remaining_entry_fee - estimated_exit_fee
                peak_equity = max(peak_equity, equity)
                if peak_equity > 0:
                    max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)
                if exit_reason:
                    exit_index = candle_index
                    break

            if exit_price is None:
                exit_index = end_index
                close = candles[end_index]["close"]
                exit_price = close * (
                    1 - self.slippage_rate if direction == "LONG" else 1 + self.slippage_rate
                )
                exit_reason = "end_of_data"

            remaining_exit_fee = remaining_quantity * exit_price * self.fee_rate
            remaining_gross_pnl = remaining_quantity * (
                exit_price - entry if direction == "LONG" else entry - exit_price
            )
            remaining_net_pnl = remaining_gross_pnl - remaining_entry_fee - remaining_exit_fee
            balance += remaining_net_pnl
            gross_pnl = partial_gross_pnl + remaining_gross_pnl
            exit_fee = partial_exit_fee + remaining_exit_fee
            net_pnl = partial_net_pnl + remaining_net_pnl
            peak_equity = max(peak_equity, balance)
            if peak_equity > 0:
                max_drawdown = max(max_drawdown, (peak_equity - balance) / peak_equity)
            trade_candles = candles[entry_index:exit_index + 1]
            if direction == "LONG":
                max_favorable = max((item["high"] - entry for item in trade_candles), default=0.0)
                max_adverse = max((entry - item["low"] for item in trade_candles), default=0.0)
            else:
                max_favorable = max((entry - item["low"] for item in trade_candles), default=0.0)
                max_adverse = max((item["high"] - entry for item in trade_candles), default=0.0)
            mfe_r = max(0.0, max_favorable) / risk_distance
            mae_r = max(0.0, max_adverse) / risk_distance
            cost_in_r = (entry * self.round_trip_cost_rate) / risk_distance

            trades.append({
                "direction": direction,
                "score": signal.get("score"),
                "reasons": signal.get("reasons", []),
                "signal_time": candles[index]["time"],
                "entry_time": candles[entry_index]["time"],
                "exit_time": candles[exit_index]["time"],
                "signal_entry": round(signal_entry, 8),
                "entry": round(entry, 8),
                "exit": round(exit_price, 8),
                "stop_loss": round(stop, 8),
                "take_profit_1": round(target_1, 8),
                "take_profit_2": round(target_2, 8),
                "quantity": round(quantity, 8),
                "tp1_hit": tp1_hit,
                "tp2_hit": tp2_hit,
                "cost_stop_activated": cost_stop_active,
                "cost_stop_activation_r": self.cost_stop_activation_r,
                "cost_aware_stop_price": round(cost_stop_price, 8) if cost_stop_active else None,
                "mfe_r": round(mfe_r, 8),
                "mae_r": round(mae_r, 8),
                "cost_in_r": round(cost_in_r, 8),
                "tp1_partial_quantity": round(partial_quantity, 8),
                "tp1_exit": round(partial_exit_price, 8) if partial_exit_price is not None else None,
                "tp1_exit_fee": round(partial_exit_fee, 8),
                "tp1_net_pnl": round(partial_net_pnl, 8),
                "remaining_quantity": round(remaining_quantity, 8),
                "stop_after_tp1": (
                    round(cost_stop_price, 8) if cost_stop_active
                    else round(stop, 8) if tp1_hit else None
                ),
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
        tp1_hits = sum(1 for trade in trades if trade["tp1_hit"])
        tp2_hits = sum(1 for trade in trades if trade["tp2_hit"])
        return {
            "mode": "paper",
            "strategy": "AdvancedStrategy",
            "initial_balance": round(self.initial_balance, 2),
            "final_balance": round(balance, 2),
            "net_profit": round(total_pnl, 2),
            "return_percent": round(total_pnl / self.initial_balance * 100, 2),
            "total_trades": len(trades),
            "tp1_hits": tp1_hits,
            "tp2_hits": tp2_hits,
            "tp2_hit_rate_percent": round(tp2_hits / len(trades) * 100, 4) if trades else 0.0,
            "tp2_hit_rate_after_tp1_percent": (
                round(tp2_hits / tp1_hits * 100, 4) if tp1_hits else 0.0
            ),
            "average_mfe_r": round(sum(trade["mfe_r"] for trade in trades) / len(trades), 6) if trades else None,
            "average_mae_r": round(sum(trade["mae_r"] for trade in trades) / len(trades), 6) if trades else None,
            "average_cost_in_r": round(sum(trade["cost_in_r"] for trade in trades) / len(trades), 6) if trades else None,
            "skipped_signals": skipped_signals,
            "expectancy_per_trade": round(total_pnl / len(trades), 4) if trades else None,
            "win_rate_percent": round(len(winners) / len(trades) * 100, 2) if trades else 0.0,
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
            "max_drawdown_percent": round(max_drawdown * 100, 2),
            "fee_rate": self.fee_rate,
            "slippage_rate": self.slippage_rate,
            "risk_per_trade": self.risk_per_trade,
            "total_fees": round(sum(trade["entry_fee"] + trade["exit_fee"] for trade in trades), 8),
            "take_profit_model": "half_exit_at_1r_then_cost_aware_stop_after_1_5r_or_tp2",
            "trades": trades,
        }
