from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from services.market_services import MarketService

from indicators.ema import calculate_ema
from indicators.rsi import calculate_rsi
from indicators.macd import calculate_macd
from indicators.vwap import calculate_vwap
from indicators.atr import calculate_atr

from strategies.ema_rsi_strategy import EmaRsiStrategy
from strategies.advanced_strategy import AdvancedStrategy
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from strategies.advanced_strategy import AdvancedStrategy
from services.backtest_service import BacktestService
from services.backtest_review import review_backtest

app = FastAPI(title="AI Trader API")
market_service = MarketService("SOLUSDT")
strategy = EmaRsiStrategy()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "project": "AI Trader API",
        "status": "running",
        "mode": "paper"
     }

@app.get("/health")
def health():
    return {"status": "ok"}    

@app.get("/api/dashboard")
def dashboard():
    return {
        "symbol": "SOL/USDT",
        "mode": "paper",
        "bot_status": "ready",
        "balance": 10000,
        "positions": [],
        "data_type": "simulated"
    }

@app.get("/api/price")
def get_price():
    price = market_service.get_price()

    return {
        "symbol": "SOL/USDT",
        "price": price,
        "source": "Binance",
        "data_type": "real_market_data"
    }

@app.get("/api/candles")
def get_candles():
    rows = market_service.get_candles(
        interval="5m",
        limit=100
    )

    return {
        "symbol": "SOL/USDT",
        "interval": "5m",
        "candles": [
            {
                "time": int(row[0] / 1000),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5])
            }
            for row in rows
        ]
    }
def calculate_ema(values, period):
    multiplier = 2 / (period + 1)
    ema = values[0]

    for price in values[1:]:
        ema = (price - ema) * multiplier + ema

    return ema



@app.get("/api/signal")
def get_signal():
    rows = market_service.get_candles(
        interval="5m",
        limit=100
    )

    closes = [float(row[4]) for row in rows]

    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)
    rsi = calculate_rsi(closes, 14)

    signal = strategy.generate_signal(
        ema9=ema9,
        ema21=ema21,
        rsi=rsi
    )

    return {
        "symbol": "SOL/USDT",
        "signal": signal,
        "price": closes[-1],
        "ema9": round(ema9, 4),
        "ema21": round(ema21, 4),
        "rsi": round(rsi, 2),
        "mode": "paper"
    }


@app.get("/api/signal/v2")
def get_signal_v2():
    try:
        # Obtener velas de Binance
        raw_candles = market_service.get_candles(
            interval="5m",
            limit=100
        )

        # Convertir las velas al formato que usan los indicadores
        candles = [
            {
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
            for row in raw_candles
        ]

        closes = [candle["close"] for candle in candles]

        # Calcular medias móviles
        ema_fast = calculate_ema(closes[-9:], 9)
        ema_slow = calculate_ema(closes[-21:], 21)
        ema_trend = calculate_ema(closes[-50:], 50)

        # Calcular indicadores
        rsi = calculate_rsi(closes, period=14)
        macd = calculate_macd(closes)
        vwap = calculate_vwap(candles)
        atr = calculate_atr(candles, period=14)

        # Evaluar la estrategia avanzada
        advanced_strategy = AdvancedStrategy()

        result = advanced_strategy.evaluate(
            candles=candles,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            ema_trend=ema_trend,
            rsi=rsi,
            macd=macd,
            vwap=vwap,
            atr=atr,
        )

        result["symbol"] = "SOL/USDT"
        result["mode"] = "paper"

        return result

    except Exception as error:
        return {
            "error": str(error),
            "symbol": "SOL/USDT",
            "mode": "paper",
        }
    
app.mount(
    "/dashboard",
    StaticFiles(
        directory=str(Path(__file__).resolve().parent.parent / "frontend"),
        html=True,
    ),
    name="dashboard",
)

@app.get("/api/backtest")
def run_backtest():
    try:
        print("BACKTEST 1: solicitando velas", flush=True)

        # Descargar hasta 1000 velas históricas de 5 minutos
        raw_candles = market_service.get_candles(
            interval="5m",
            limit=5000,
        )
        print(f"BACKTEST 2: velas recibidas: {len(raw_candles)}", flush=True)

        # Ejecutar el backtest con capital virtual
        backtester = BacktestService(
            initial_balance=10000.0,
            fee_rate=0.001,
            slippage_rate=0.0005,
            risk_per_trade=0.01,
        )

        print("BACKTEST 3: iniciando cálculo", flush=True)

        result = backtester.run(raw_candles)
        result["quality_review"] = review_backtest(result, raw_candles)

        print("BACKTEST 4: cálculo terminado", flush=True)

        result["symbol"] = "SOL/USDT"
        result["interval"] = "5m"
        result["mode"] = "paper"

        return result

    except Exception as error:
        return {
            "error": str(error),
            "symbol": "SOL/USDT",
            "mode": "paper",
        }



    
