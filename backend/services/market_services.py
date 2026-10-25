
import requests


class MarketService:
    def __init__(self, symbol="SOLUSDT"):
        self.symbol = symbol
        self.base_url = "https://data-api.binance.vision/api/v3"

   
    def get_price(self):
        response = requests.get(
            f"{self.base_url}/ticker/price",
            params={"symbol": self.symbol},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return float(data["price"])



    def get_candles(self, interval="5m", limit=100):
        """Descarga velas históricas por lotes de hasta 1000."""
        limit = int(limit)

        if limit < 1:
            raise ValueError("El límite de velas debe ser mayor que cero")

        candles = []
        end_time = None

        while len(candles) < limit:
            batch_limit = min(1000, limit - len(candles))

            params = {
                "symbol": self.symbol,
                "interval": interval,
                "limit": batch_limit,
            }

            if end_time is not None:
                params["endTime"] = end_time

            response = requests.get(
                f"{self.base_url}/klines",
                params=params,
                timeout=10,
            )
            response.raise_for_status()

            batch = response.json()

            if not batch:
                break

            # Evitar duplicados al consultar páginas anteriores.
            existing_times = {int(candle[0]) for candle in candles}
            batch = [
                candle for candle in batch
                if int(candle[0]) not in existing_times
            ]

            if not batch:
                break

            # Binance devuelve las velas en orden cronológico.
            candles = batch + candles

            # Continuar hacia atrás desde la vela más antigua.
            end_time = int(batch[0][0]) - 1

            if len(candles) >= limit:
                break

        return candles[-limit:]
