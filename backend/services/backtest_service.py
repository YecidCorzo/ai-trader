
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
    ):
        self.initial_balance = float(initial_balance)
        self.fee_rate = float(fee_rate)
        self.slippage_rate = float(slippage_rate)
        self.risk_per_trade = float(risk_per_trade)
        self.atr_multiplier = float(atr_multiplier)
        self.reward_risk = float(reward_risk)

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
        result = [None] * len(closes)

        for i in range(period, len(closes)):
            changes = [
                closes[j] - closes[j - 1]
                for j in range(i - period + 1, i + 1)
            ]

            gains = [max(change, 0) for change in changes]
            losses = [max(-change, 0) for change in changes]

            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period

            if avg_gain == 0 and avg_loss == 0:
                result[i] = 50.0
            elif avg_loss == 0:
                result[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                result[i] = 100 - (100 / (1 + rs))

        return result

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
    def _resolve_candle_exit(direction, candle, stop, target, slippage_rate):
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
            if open_price >= stop:
                return open_price * (1 + slippage_rate), "stop_loss"
            if candle["high"] >= stop:
                return stop * (1 + slippage_rate), "stop_loss"
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
        if fast_period < 1 or slow_period < 1 or rsi_period < 1:
            raise ValueError("Los periodos de los indicadores deben ser positivos")

        if fast_period >= slow_period:
            raise ValueError("fast_period debe ser menor que slow_period")

        minimum_candles = max(slow_period, rsi_period + 1, 15) + 20

        if len(raw_candles) < minimum_candles:
            raise ValueError(
                "Se necesitan más velas para realizar el backtest"
            )

        if self.initial_balance <= 0:
            raise ValueError("El capital inicial debe ser positivo")

        if not 0 < self.risk_per_trade <= 0.01:
            raise ValueError("El riesgo por operación debe estar entre 0 y 1 %")

        # Convertir las velas a un formato uniforme.
        candles = []

        for row in raw_candles:
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
                candle = {
                    "time": row[0],
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }

            if (
                candle["open"] <= 0
                or candle["high"] <= 0
                or candle["low"] <= 0
                or candle["close"] <= 0
            ):
                raise ValueError("Se encontró una vela con precios inválidos")

            candles.append(candle)

        # Verificar que los datos estén ordenados cronológicamente.
        timestamps = [candle["time"] for candle in candles]

        if any(
            timestamps[i] >= timestamps[i + 1]
            for i in range(len(timestamps) - 1)
        ):
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

            exit_price = None
            exit_index = None
            exit_reason = None

            # Buscar el stop o el objetivo desde la vela de entrada.
            for j in range(entry_candle_index, len(candles)):
                candle = candles[j]

                exit_price, exit_reason = self._resolve_candle_exit(
                    direction=direction,
                    candle=candle,
                    stop=stop,
                    target=target,
                    slippage_rate=self.slippage_rate,
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

            drawdown = (
                (peak_balance - balance) / peak_balance
                if peak_balance > 0
                else 0
            )

            max_drawdown = max(max_drawdown, drawdown)

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

        return {
            "mode": "paper",
            "initial_balance": round(self.initial_balance, 2),
            "final_balance": round(balance, 2),
            "net_profit": round(total_pnl, 2),
            "return_percent": round(
                total_pnl / self.initial_balance * 100, 2
            ),
            "total_trades": len(trades),
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
            "trades": trades,
        }
