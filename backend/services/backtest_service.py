
import math

from indicators.rsi import calculate_rsi_series


class BacktestService:
    """
    Backtest histórico para PAPER TRADING.

    Las señales se calculan al cierre de una vela.
    La entrada se simula en la apertura de la siguiente vela.
    Incluye comisiones, deslizamiento y stops basados en ATR.
    """

    def __init__(
        self,
        initial_balance=10000.0,
        fee_rate=0.001,
        slippage_rate=0.0005,
        risk_per_trade=0.01,
        atr_multiplier=1.5,
        reward_risk=2.0,
        short_maintenance_margin_rate=0.25,
    ):
        self.initial_balance = float(initial_balance)
        self.fee_rate = float(fee_rate)
        self.slippage_rate = float(slippage_rate)
        self.risk_per_trade = float(risk_per_trade)
        self.atr_multiplier = float(atr_multiplier)
        self.reward_risk = float(reward_risk)
        self.short_maintenance_margin_rate = float(short_maintenance_margin_rate)

        numeric_settings = {
            "initial_balance": self.initial_balance,
            "fee_rate": self.fee_rate,
            "slippage_rate": self.slippage_rate,
            "risk_per_trade": self.risk_per_trade,
            "atr_multiplier": self.atr_multiplier,
            "reward_risk": self.reward_risk,
            "short_maintenance_margin_rate": self.short_maintenance_margin_rate,
        }
        if not all(math.isfinite(value) for value in numeric_settings.values()):
            raise ValueError("Los parámetros del backtest deben ser valores finitos")
        if self.initial_balance <= 0:
            raise ValueError("El capital inicial debe ser positivo")
        if not 0 <= self.fee_rate < 1:
            raise ValueError("fee_rate debe estar entre 0 y 1")
        if not 0 <= self.slippage_rate < 1:
            raise ValueError("slippage_rate debe estar entre 0 y 1")
        if not 0 < self.risk_per_trade <= 0.01:
            raise ValueError("El riesgo por operación debe estar entre 0 y 1 %")
        if self.atr_multiplier <= 0 or self.reward_risk <= 0:
            raise ValueError("atr_multiplier y reward_risk deben ser positivos")
        if not 0 < self.short_maintenance_margin_rate < 1:
            raise ValueError("short_maintenance_margin_rate debe estar entre 0 y 1")

    @staticmethod
    def _ema_series(values, period):
        result = []
        multiplier = 2 / (period + 1)

        for value in values:
            value = float(value)

            if not result:
                result.append(value)
            else:
                ema = (
                    (value - result[-1]) * multiplier
                    + result[-1]
                )
                result.append(ema)

        return result

    @staticmethod
    def _rsi_series(closes, period=14):
        """Use the shared Wilder RSI implementation used by live signals."""
        return calculate_rsi_series(closes, period)

    @staticmethod
    def _atr_series(candles, period=14):
        result = [None] * len(candles)
        true_ranges = []

        for i, candle in enumerate(candles):
            high = candle["high"]
            low = candle["low"]

            if i == 0:
                true_range = high - low
            else:
                previous_close = candles[i - 1]["close"]

                true_range = max(
                    high - low,
                    abs(high - previous_close),
                    abs(low - previous_close),
                )

            true_ranges.append(true_range)

            if i >= period:
                result[i] = (
                    sum(true_ranges[i - period + 1:i + 1])
                    / period
                )

        return result

    @staticmethod
    def _update_equity_drawdown(
        balance,
        direction,
        entry,
        quantity,
        mark_price,
        entry_fee,
        fee_rate,
        peak_equity,
        max_drawdown,
    ):
        """Update drawdown using marked-to-market equity, including open trades."""
        if direction == "LONG":
            unrealized_pnl = quantity * (mark_price - entry)
        else:
            unrealized_pnl = quantity * (entry - mark_price)

        estimated_exit_fee = quantity * mark_price * fee_rate
        equity = balance + unrealized_pnl - entry_fee - estimated_exit_fee
        peak_equity = max(peak_equity, equity)
        drawdown = (
            (peak_equity - equity) / peak_equity
            if peak_equity > 0
            else 0.0
        )
        return peak_equity, max(max_drawdown, drawdown)

    @staticmethod
    def _short_liquidation_price(entry, fee_rate, maintenance_margin_rate):
        """Isolated 1x short liquidation threshold, including estimated fees.

        Collateral is the full entry notional. The threshold is reached when
        collateral plus unrealized PnL, less entry/estimated exit fees, equals
        maintenance margin. This is a simplified paper model, not an exchange
        liquidation simulator.
        """
        denominator = 1 + fee_rate + maintenance_margin_rate
        if entry <= 0 or denominator <= 0:
            raise ValueError("Parámetros inválidos para calcular liquidación")
        return entry * (2 - fee_rate) / denominator

    @staticmethod
    def _resolve_candle_exit(
        direction, candle, stop, target, slippage_rate, liquidation_price=None
    ):
        """Resolve OHLC stop/target touches conservatively.

        If price gaps through a stop, fill at the candle open (worse than the
        stop), not at the stop price. If both stop and target are touched in
        one candle, assume the stop happened first. Limit targets never receive
        favorable gap price improvement.
        """
        open_price = candle["open"]
        if direction == "LONG":
            if open_price <= stop:
                return open_price * (1 - slippage_rate), "stop_loss"
            if candle["low"] <= stop:
                return stop * (1 - slippage_rate), "stop_loss"
            if candle["high"] >= target:
                return target * (1 - slippage_rate), "take_profit"
        else:
            # A gap beyond liquidation is filled at the opening price.
            if liquidation_price is not None and open_price >= liquidation_price:
                return open_price * (1 + slippage_rate), "liquidation"
            if open_price >= stop:
                return open_price * (1 + slippage_rate), "stop_loss"
            if candle["high"] >= stop:
                return stop * (1 + slippage_rate), "stop_loss"
            if liquidation_price is not None and candle["high"] >= liquidation_price:
                return liquidation_price * (1 + slippage_rate), "liquidation"
            if candle["low"] <= target:
                return target * (1 + slippage_rate), "take_profit"
        return None, None

    def run(
        self,
        raw_candles,
        fast_period=9,
        slow_period=21,
        rsi_period=14,
        rsi_long_min=50,
        rsi_short_max=50,
    ):
        if any(
            not isinstance(period, int) or isinstance(period, bool) or period < 1
            for period in (fast_period, slow_period, rsi_period)
        ):
            raise ValueError("Los periodos de los indicadores deben ser enteros positivos")

        if not 0 <= rsi_long_min <= 100 or not 0 <= rsi_short_max <= 100:
            raise ValueError("Los umbrales RSI deben estar entre 0 y 100")

        if fast_period >= slow_period:
            raise ValueError("fast_period debe ser menor que slow_period")

        minimum_candles = max(slow_period, rsi_period + 1, 15) + 20

        if len(raw_candles) < minimum_candles:
            raise ValueError(
                "Se necesitan más velas para realizar el backtest"
            )

        # Convertir las velas a un formato uniforme.
        candles = []

        for row in raw_candles:
            try:
                if isinstance(row, dict):
                    candle = {
                        "time": row.get("time", row.get("timestamp")),
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row.get("volume", 0)),
                    }
                else:
                    if len(row) < 6:
                        raise ValueError("La vela debe contener al menos 6 campos")
                    candle = {
                        "time": row[0],
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    }
            except (KeyError, TypeError, IndexError) as error:
                raise ValueError("Formato de vela inválido o incompleto") from error

            prices = [candle[key] for key in ("open", "high", "low", "close", "volume")]
            if not all(math.isfinite(value) for value in prices):
                raise ValueError("La vela contiene precios o volumen no finitos")
            if any(candle[key] <= 0 for key in ("open", "high", "low", "close")):
                raise ValueError("Se encontró una vela con precios inválidos")
            if candle["volume"] < 0:
                raise ValueError("El volumen no puede ser negativo")
            if (
                candle["high"] < max(candle["open"], candle["close"], candle["low"])
                or candle["low"] > min(candle["open"], candle["close"], candle["high"])
            ):
                raise ValueError("La vela contiene valores OHLC inconsistentes")
            if candle["time"] is None:
                raise ValueError("Cada vela debe incluir timestamp")

            candles.append(candle)

        # Verificar que los datos estén ordenados cronológicamente.
        timestamps = [candle["time"] for candle in candles]

        try:
            timestamps_are_invalid = any(
                timestamps[i] >= timestamps[i + 1]
                for i in range(len(timestamps) - 1)
            )
        except TypeError as error:
            raise ValueError("Los timestamps deben usar un formato consistente") from error

        if timestamps_are_invalid:
            raise ValueError(
                "Las velas deben estar ordenadas cronológicamente y sin duplicados"
            )

        closes = [candle["close"] for candle in candles]

        ema_fast = self._ema_series(closes, fast_period)
        ema_slow = self._ema_series(closes, slow_period)
        rsi_values = self._rsi_series(closes, rsi_period)
        atr_values = self._atr_series(candles, 14)

        balance = self.initial_balance
        peak_balance = balance
        max_drawdown = 0.0
        trades = []

        i = max(slow_period, rsi_period + 1, 15)

        # Bucle principal: cada operación se procesa una sola vez.
        while i < len(candles) - 1:
            rsi = rsi_values[i]
            atr = atr_values[i]

            if rsi is None or atr is None or atr <= 0:
                i += 1
                continue

            # Señales por cruce EMA, confirmadas al cierre de la vela.
            long_signal = (
                ema_fast[i - 1] <= ema_slow[i - 1]
                and ema_fast[i] > ema_slow[i]
                and rsi >= rsi_long_min
            )

            short_signal = (
                ema_fast[i - 1] >= ema_slow[i - 1]
                and ema_fast[i] < ema_slow[i]
                and rsi <= rsi_short_max
            )

            if not long_signal and not short_signal:
                i += 1
                continue

            direction = "LONG" if long_signal else "SHORT"

            entry_candle_index = i + 1
            next_candle = candles[entry_candle_index]

            # Aplicar deslizamiento desfavorable en la entrada.
            raw_entry = next_candle["open"]

            if direction == "LONG":
                entry = raw_entry * (1 + self.slippage_rate)
                stop = entry - atr * self.atr_multiplier
                target = entry + (entry - stop) * self.reward_risk
            else:
                entry = raw_entry * (1 - self.slippage_rate)
                stop = entry + atr * self.atr_multiplier
                target = entry - (stop - entry) * self.reward_risk

            risk_amount = balance * self.risk_per_trade

            # Estimar la pérdida por unidad incluyendo costes de salida.
            if direction == "LONG":
                estimated_exit = stop * (1 - self.slippage_rate)
            else:
                estimated_exit = stop * (1 + self.slippage_rate)

            estimated_loss_per_unit = (
                abs(entry - estimated_exit)
                + entry * self.fee_rate
                + estimated_exit * self.fee_rate
            )

            if estimated_loss_per_unit <= 0:
                i += 1
                continue

            quantity = risk_amount / estimated_loss_per_unit

            # Limitar el nominal y la comisión de entrada al capital disponible.
            quantity = min(
                quantity,
                balance / (entry * (1 + self.fee_rate)),
            )

            if quantity <= 0:
                break

            entry_fee = quantity * entry * self.fee_rate

            liquidation_price = (
                self._short_liquidation_price(
                    entry,
                    self.fee_rate,
                    self.short_maintenance_margin_rate,
                )
                if direction == "SHORT"
                else None
            )

            exit_price = None
            exit_index = None
            exit_reason = None

            # Marcar a mercado cada vela mientras la posición está abierta.
            for j in range(entry_candle_index, len(candles)):
                candle = candles[j]

                exit_price, exit_reason = self._resolve_candle_exit(
                    direction=direction,
                    candle=candle,
                    stop=stop,
                    target=target,
                    slippage_rate=self.slippage_rate,
                    liquidation_price=liquidation_price,
                )

                mark_price = exit_price if exit_reason is not None else candle["close"]
                peak_balance, max_drawdown = self._update_equity_drawdown(
                    balance=balance,
                    direction=direction,
                    entry=entry,
                    quantity=quantity,
                    mark_price=mark_price,
                    entry_fee=entry_fee,
                    fee_rate=self.fee_rate,
                    peak_equity=peak_balance,
                    max_drawdown=max_drawdown,
                )

                if exit_reason is not None:
                    exit_index = j
                    break

            # Si no se alcanza stop ni objetivo, cerrar al final del histórico.
            if exit_price is None:
                exit_index = len(candles) - 1
                last_close = candles[exit_index]["close"]

                if direction == "LONG":
                    exit_price = last_close * (1 - self.slippage_rate)
                else:
                    exit_price = last_close * (1 + self.slippage_rate)

                exit_reason = "end_of_data"

            if direction == "LONG":
                gross_pnl = quantity * (exit_price - entry)
            else:
                gross_pnl = quantity * (entry - exit_price)

            exit_fee = quantity * exit_price * self.fee_rate
            net_pnl = gross_pnl - entry_fee - exit_fee
            balance += net_pnl

            peak_balance = max(peak_balance, balance)
            realized_drawdown = (
                (peak_balance - balance) / peak_balance
                if peak_balance > 0
                else 0.0
            )
            max_drawdown = max(max_drawdown, realized_drawdown)

            trades.append({
                "direction": direction,
                "entry": round(entry, 6),
                "exit": round(exit_price, 6),
                "quantity": round(quantity, 6),
                "gross_pnl": round(gross_pnl, 4),
                "fees": round(entry_fee + exit_fee, 4),
                "net_pnl": round(net_pnl, 4),
                "balance": round(balance, 4),
                "reason": exit_reason,
                "entry_time": candles[entry_candle_index]["time"],
                "exit_time": candles[exit_index]["time"],
            })

            # Avanzar hasta la vela posterior al cierre de la operación.
            i = exit_index + 1

        # Resumen de resultados.
        winners = [trade for trade in trades if trade["net_pnl"] > 0]
        losers = [trade for trade in trades if trade["net_pnl"] <= 0]

        total_pnl = balance - self.initial_balance

        gross_profit = sum(trade["net_pnl"] for trade in winners)
        gross_loss = abs(sum(trade["net_pnl"] for trade in losers))

        profit_factor = (
            round(gross_profit / gross_loss, 4)
            if gross_loss > 0
            else None
        )

        # Métricas adicionales para auditar el backtest.
        total_fees = sum(trade["fees"] for trade in trades)
        gross_pnl_before_fees = sum(
            trade["gross_pnl"] for trade in trades
        )

        long_net_pnl = sum(
            trade["net_pnl"]
            for trade in trades
            if trade["direction"] == "LONG"
        )

        short_net_pnl = sum(
            trade["net_pnl"]
            for trade in trades
            if trade["direction"] == "SHORT"
        )

        stop_loss_count = sum(
            trade["reason"] == "stop_loss"
            for trade in trades
        )

        take_profit_count = sum(
            trade["reason"] == "take_profit"
            for trade in trades
        )

        end_of_data_count = sum(
            trade["reason"] == "end_of_data"
            for trade in trades
        )
        liquidation_count = sum(
            trade["reason"] == "liquidation"
            for trade in trades
        )

        # Net expectancy and side-level diagnostics. These are descriptive
        # statistics from the executed sample, not a forecast or win probability.
        def side_metrics(side_trades):
            side_winners = [trade for trade in side_trades if trade["net_pnl"] > 0]
            side_losers = [trade for trade in side_trades if trade["net_pnl"] < 0]
            side_total = len(side_trades)
            return {
                "trade_count": side_total,
                "net_pnl": round(sum(trade["net_pnl"] for trade in side_trades), 4),
                "expectancy_per_trade": round(
                    sum(trade["net_pnl"] for trade in side_trades) / side_total, 4
                ) if side_total else None,
                "win_rate_percent": round(len(side_winners) / side_total * 100, 2)
                if side_total else None,
                "average_win": round(
                    sum(trade["net_pnl"] for trade in side_winners) / len(side_winners), 4
                ) if side_winners else None,
                "average_loss": round(
                    sum(trade["net_pnl"] for trade in side_losers) / len(side_losers), 4
                ) if side_losers else None,
            }

        losing_trades = [trade for trade in trades if trade["net_pnl"] < 0]
        long_trades = [trade for trade in trades if trade["direction"] == "LONG"]
        short_trades = [trade for trade in trades if trade["direction"] == "SHORT"]
        total_net_pnl = sum(trade["net_pnl"] for trade in trades)

        return {
            "mode": "paper",
            "initial_balance": round(self.initial_balance, 2),
            "final_balance": round(balance, 2),
            "net_profit": round(total_pnl, 2),
            "return_percent": round(
                total_pnl / self.initial_balance * 100, 2
            ),
            "total_trades": len(trades),
            "expectancy_per_trade": round(total_net_pnl / len(trades), 4) if trades else None,
            "average_winning_trade": round(sum(t["net_pnl"] for t in winners) / len(winners), 4) if winners else None,
            "average_losing_trade": round(sum(t["net_pnl"] for t in losing_trades) / len(losing_trades), 4) if losing_trades else None,
            "long_metrics": side_metrics(long_trades),
            "short_metrics": side_metrics(short_trades),
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "win_rate_percent": round(
                len(winners) / len(trades) * 100, 2
            ) if trades else 0,
            "profit_factor": profit_factor,
            "max_drawdown_percent": round(max_drawdown * 100, 2),
            "fee_rate": self.fee_rate,
            "slippage_rate": self.slippage_rate,
            "total_fees": round(total_fees, 2),
            "gross_pnl_before_fees": round(gross_pnl_before_fees, 2),
            "long_net_pnl": round(long_net_pnl, 2),
            "short_net_pnl": round(short_net_pnl, 2),
            "stop_loss_count": stop_loss_count,
            "take_profit_count": take_profit_count,
            "end_of_data_count": end_of_data_count,
            "liquidation_count": liquidation_count,
            "short_margin_model": "isolated_1x_full_notional_collateral",
            "short_maintenance_margin_rate": self.short_maintenance_margin_rate,
            "trades": trades,
        }
