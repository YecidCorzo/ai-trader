from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import logging
import os
import sys

from services.market_services import MarketService, MarketDataError
from services.signal_validation import validate_signal_history
from indicators.ema import calculate_ema, calculate_ema_series
from indicators.rsi import calculate_rsi
from indicators.macd import calculate_macd
from indicators.vwap import calculate_vwap
from indicators.atr import calculate_atr
from strategies.ema_rsi_strategy import EmaRsiStrategy
from strategies.advanced_strategy import AdvancedStrategy
from services.backtest_service import BacktestService
from services.advanced_strategy_backtest import AdvancedStrategyBacktestService
from services.backtest_review import review_backtest
from services.backtest_research import run_walk_forward_backtests, run_advanced_strategy_walk_forward_backtests
from services.strategy_acceptance import (
    evaluate_advanced_strategy_go_no_go,
    ADVANCED_STRATEGY_ACCEPTANCE_CONFIG,
)
from services.multi_timeframe_analysis import MultiTimeframeAnalysisService
try:
    from backend.api.paper_routes import router as paper_router
except ImportError:
    from api.paper_routes import router as paper_router
try:
    from backend.api.coinbase_routes import router as coinbase_router
except ImportError:
    from api.coinbase_routes import router as coinbase_router

logger = logging.getLogger(__name__)


def _market_data_http_error(error):
    logger.warning("Market-data upstream failure: %s", type(error).__name__)
    return HTTPException(
        status_code=error.status_code,
        detail="Proveedor de datos de mercado no disponible",
    )


def _internal_server_error(operation):
    error = sys.exc_info()[1]
    if isinstance(error, MarketDataError):
        return _market_data_http_error(error)
    logger.exception("Unexpected error while executing %s", operation)
    return HTTPException(status_code=500, detail="Error interno del servidor")


app = FastAPI(title="AI Trader API")
app.include_router(paper_router)
app.include_router(coinbase_router)
market_service = MarketService("SOLUSDT")
strategy = EmaRsiStrategy()
cors_origins = [
    origin.strip()
    for origin in os.environ.get(
        "AI_TRADER_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
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
        "bot_status": "account_not_configured",
        "account_status": "not_configured",
        "balance": None,
        "equity": None,
        "positions": [],
        "data_type": "not_configured",
        "message": "Crea una cuenta PAPER con capital inicial explícito antes de iniciar la simulación."
    }

@app.get("/api/price")
def get_price():
    try:
        price = market_service.get_price()
    except MarketDataError as error:
        raise _market_data_http_error(error) from None

    return {
        "symbol": "SOL/USDT",
        "price": price,
        "source": "Binance",
        "data_type": "real_market_data"
    }

@app.get("/api/candles")
def get_candles():
    try:
        rows = market_service.get_candles(
            interval="5m",
            limit=100
        )
    except MarketDataError as error:
        raise _market_data_http_error(error) from None

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
@app.get("/api/signal")
def get_signal():
    try:
        rows = market_service.get_candles(
            interval="5m",
            limit=5000,
            closed_only=True,
        )
    except MarketDataError as error:
        raise _market_data_http_error(error) from None

    closes = [float(row[4]) for row in rows]

    try:
        validate_signal_history(closes, minimum=15)
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    ema9_series = calculate_ema_series(closes, 9)
    ema21_series = calculate_ema_series(closes, 21)
    ema9 = ema9_series[-1]
    ema21 = ema21_series[-1]
    rsi = calculate_rsi(closes, 14)

    # Compare consecutive closed-candle EMA values so the live endpoint
    # follows the same crossover rule as BacktestService.
    signal = strategy.generate_signal(
        ema9=ema9,
        ema21=ema21,
        rsi=rsi,
        prev_ema9=ema9_series[-2],
        prev_ema21=ema21_series[-2],
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


@app.get("/api/signal/multi-timeframe")
def get_multi_timeframe_signal():
    """Return 1h/4h closed-candle signals and strict directional consensus."""
    try:
        service = MultiTimeframeAnalysisService(market_service, limit=500)
        return service.run()
    except Exception:
        raise _internal_server_error("multi_timeframe_signal") from None

@app.get("/api/signal/v2")
def get_signal_v2():
    try:
        # Obtener velas de Binance
        raw_candles = market_service.get_candles(
            interval="1h",
            limit=5000,
            closed_only=True,
        )

        # Convertir las velas al formato que usan los indicadores
        candles = [
            {
                "time": int(row[0] / 1000),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
            for row in raw_candles
        ]

        closes = [candle["close"] for candle in candles]
        validate_signal_history(closes, minimum=50)

        # Calcular medias móviles
        # Use the complete available history for each EMA. Truncating to
        # exactly one period changes the EMA seed and diverges from backtests.
        ema_fast = calculate_ema(closes, 9)
        ema_slow = calculate_ema(closes, 21)
        ema_trend_series = calculate_ema_series(closes, 50)
        ema_trend = ema_trend_series[-1]
        ema_trend_slope = (
            (ema_trend_series[-1] - ema_trend_series[-6]) / ema_trend_series[-6]
            if len(ema_trend_series) >= 6 and ema_trend_series[-6] != 0
            else None
        )

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
            ema_trend_slope=ema_trend_slope,
            rsi=rsi,
            macd=macd,
            vwap=vwap,
            atr=atr,
        )

        result["symbol"] = "SOL/USDT"
        result["mode"] = "paper"

        return result

    except HTTPException:
        raise
    except Exception:
        raise _internal_server_error("signal_v2") from None

app.mount(
    "/dashboard",
    StaticFiles(
        directory=str(Path(__file__).resolve().parent.parent / "frontend"),
        html=True,
    ),
    name="dashboard",
)

@app.get("/api/backtest")
def run_backtest(
    limit: int = Query(5000, ge=100, le=100000),
    interval: str = Query("5m"),
):
    allowed_intervals = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}
    if interval not in allowed_intervals:
        raise HTTPException(status_code=400, detail="Intervalo no soportado")

    try:
        print("BACKTEST 1: solicitando velas", flush=True)

        # MarketService pagina internamente; el límite permite ampliar
        # el histórico sin duplicar la lógica de descarga.
        raw_candles = market_service.get_candles(
            interval=interval,
            limit=limit,
            closed_only=True,
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
        result["interval"] = interval
        result["candles_requested"] = limit
        result["candles_received"] = len(raw_candles)
        if raw_candles:
            result["history_start"] = raw_candles[0][0]
            result["history_end"] = raw_candles[-1][0]
        result["mode"] = "paper"

        return result

    except HTTPException:
        raise
    except Exception:
        raise _internal_server_error("backtest") from None



    


@app.get("/api/backtest/advanced")
def run_advanced_backtest(
    limit: int = Query(5000, ge=100, le=100000),
    interval: str = Query("1h"),
):
    """Backtest the same AdvancedStrategy.evaluate logic used by /api/signal/v2."""
    allowed_intervals = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}
    if interval not in allowed_intervals:
        raise HTTPException(status_code=400, detail="Intervalo no soportado")
    try:
        raw_candles = market_service.get_candles(
            interval=interval, limit=limit, closed_only=True,
        )
        validate_signal_history([float(row[4]) for row in raw_candles], minimum=52)
        backtester = AdvancedStrategyBacktestService(
            initial_balance=10000.0, fee_rate=0.001,
            slippage_rate=0.0005, risk_per_trade=0.01,
        )
        result = backtester.run(raw_candles)
        result.update({
            "symbol": "SOL/USDT",
            "interval": interval,
            "candles_requested": limit,
            "candles_received": len(raw_candles),
            "history_start": raw_candles[0][0],
            "history_end": raw_candles[-1][0],
            "mode": "paper",
        })
        return result
    except HTTPException:
        raise
    except Exception:
        raise _internal_server_error("advanced_strategy_backtest") from None

@app.get("/api/backtest/advanced/acceptance")
def get_advanced_strategy_acceptance():
    """Run the immutable, pre-registered SOL/USDT 1h acceptance sample."""
    config = dict(ADVANCED_STRATEGY_ACCEPTANCE_CONFIG)
    try:
        raw_candles = market_service.get_candles(
            interval=config["interval"],
            limit=config["limit"],
            closed_only=True,
        )
        raw_candles = raw_candles[-config["limit"]:]
        history_count = len(raw_candles)

        if history_count >= config["required_bars"]:
            walk_forward = run_advanced_strategy_walk_forward_backtests(
                raw_candles,
                train_size=config["train_size"],
                validation_size=config["validation_size"],
                test_size=config["test_size"],
                step_size=config["step_size"],
                backtest_kwargs={
                    "initial_balance": 10000.0,
                    "fee_rate": 0.001,
                    "slippage_rate": 0.0005,
                    "risk_per_trade": 0.01,
                },
            )
        else:
            # Insufficient real history is a published NO_GO, not a server error.
            walk_forward = {
                "total_trades": 0,
                "expectancy_per_trade": None,
                "profit_factor": None,
                "max_fold_drawdown_percent": None,
                "fold_count": 0,
                "folds": [],
                "trades": [],
            }

        decision = evaluate_advanced_strategy_go_no_go(walk_forward)
        walk_forward_summary = {
            key: value for key, value in walk_forward.items() if key != "trades"
        }
        return {
            "mode": "paper",
            "acceptance_config": config,
            "symbol": config["symbol"],
            "market_symbol": config["market_symbol"],
            "interval": config["interval"],
            "candles_requested": config["limit"],
            "candles_received": history_count,
            "history_complete": history_count >= config["limit"],
            "history_start": raw_candles[0][0] if raw_candles else None,
            "history_end": raw_candles[-1][0] if raw_candles else None,
            "decision": decision,
            "walk_forward": walk_forward_summary,
        }
    except HTTPException:
        raise
    except Exception:
        raise _internal_server_error("advanced_strategy_acceptance") from None

@app.get("/api/backtest/advanced/walk-forward")
def run_advanced_strategy_walk_forward(
    limit: int = Query(10000, ge=100, le=100000),
    interval: str = Query("1d"),
    train_size: int = Query(5000, ge=50, le=90000),
    validation_size: int = Query(1000, ge=1, le=50000),
    test_size: int = Query(1000, ge=2, le=50000),
    step_size: int = Query(1000, ge=1, le=50000),
):
    """Run fixed-parameter AdvancedStrategy chronological out-of-sample folds."""
    allowed_intervals = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}
    if interval not in allowed_intervals:
        raise HTTPException(status_code=400, detail="Intervalo no soportado")
    if step_size < test_size:
        raise HTTPException(status_code=400, detail="step_size debe ser mayor o igual que test_size")
    required = train_size + validation_size + test_size
    if required > limit:
        raise HTTPException(status_code=400, detail="limit debe cubrir train_size + validation_size + test_size")
    try:
        raw_candles = market_service.get_candles(interval=interval, limit=limit, closed_only=True)
        if len(raw_candles) < required:
            raise HTTPException(status_code=422, detail=f"Histórico insuficiente: se necesitan {required} velas y llegaron {len(raw_candles)}")
        result = run_advanced_strategy_walk_forward_backtests(
            raw_candles,
            train_size=train_size,
            validation_size=validation_size,
            test_size=test_size,
            step_size=step_size,
            backtest_kwargs={
                "initial_balance": 10000.0,
                "fee_rate": 0.001,
                "slippage_rate": 0.0005,
                "risk_per_trade": 0.01,
            },
        )
        result.update({
            "symbol": "SOL/USDT",
            "interval": interval,
            "candles_requested": limit,
            "candles_received": len(raw_candles),
            "history_start": raw_candles[0][0],
            "history_end": raw_candles[-1][0],
            "mode": "paper",
        })
        return result
    except HTTPException:
        raise
    except Exception:
        raise _internal_server_error("advanced_strategy_walk_forward") from None

@app.get("/api/backtest/walk-forward")
def run_walk_forward(
    limit: int = Query(10000, ge=100, le=100000),
    interval: str = Query("1d"),
    train_size: int = Query(5000, ge=30, le=90000),
    validation_size: int = Query(1000, ge=1, le=50000),
    test_size: int = Query(1000, ge=2, le=50000),
    step_size: int = Query(1000, ge=1, le=50000),
):
    """Run fixed-parameter chronological out-of-sample tests in PAPER mode."""
    allowed_intervals = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"}
    if interval not in allowed_intervals:
        raise HTTPException(status_code=400, detail="Intervalo no soportado")
    if test_size < 2:
        raise HTTPException(
            status_code=422,
            detail="test_size debe ser al menos 2 para calcular Buy & Hold",
        )
    if step_size < test_size:
        raise HTTPException(
            status_code=400,
            detail="step_size debe ser mayor o igual que test_size para evitar ventanas de prueba solapadas",
        )
    required = train_size + validation_size + test_size
    if required > limit:
        raise HTTPException(
            status_code=400,
            detail="limit debe cubrir train_size + validation_size + test_size",
        )
    try:
        raw_candles = market_service.get_candles(
            interval=interval,
            limit=limit,
            closed_only=True,
        )
        if len(raw_candles) < required:
            raise HTTPException(
                status_code=422,
                detail=f"Histórico insuficiente: se necesitan {required} velas y llegaron {len(raw_candles)}",
            )
        result = run_walk_forward_backtests(
            raw_candles,
            train_size=train_size,
            validation_size=validation_size,
            test_size=test_size,
            step_size=step_size,
            backtest_kwargs={
                "initial_balance": 10000.0,
                "fee_rate": 0.001,
                "slippage_rate": 0.0005,
                "risk_per_trade": 0.01,
            },
        )
        result.update({
            "symbol": "SOL/USDT",
            "interval": interval,
            "candles_requested": limit,
            "candles_received": len(raw_candles),
            "history_start": raw_candles[0][0],
            "history_end": raw_candles[-1][0],
            "mode": "paper",
        })
        return result
    except HTTPException:
        raise
    except Exception:
        raise _internal_server_error("walk_forward_backtest") from None


# Bitunix Futures is an additional read-only market-data source.
# No private API, account, position, or order endpoints are used here.
from services.bitunix_market_service import (
    BitunixMarketDataError,
    BitunixMarketService,
)
from services.market_price_comparison import MarketPriceComparisonService

bitunix_market_service = BitunixMarketService("SOLUSDT")
shadow_market_comparison = MarketPriceComparisonService(
    market_service, bitunix_market_service,
)


def _bitunix_market_data_http_error(error):
    logger.warning("Bitunix market-data upstream failure: %s", type(error).__name__)
    return HTTPException(
        status_code=error.status_code,
        detail="Proveedor Bitunix de datos de mercado no disponible",
    )


@app.get("/api/bitunix/price")
def get_bitunix_price():
    try:
        price = bitunix_market_service.get_price()
        try:
            mark_price = bitunix_market_service.get_mark_price()
        except BitunixMarketDataError:
            # Last traded price remains informational; mark price is not
            # silently substituted and is not used by PAPER risk or stops.
            mark_price = None
            logger.warning("Bitunix mark price unavailable; risk integration remains disabled")
    except BitunixMarketDataError as error:
        raise _bitunix_market_data_http_error(error) from None
    return {
        "symbol": "SOL/USDT",
        "price": price,
        "price_type": "last_traded_price_not_mark_price",
        "mark_price": mark_price,
        "mark_price_available": mark_price is not None,
        "source": "Bitunix Futures",
        "data_type": "real_market_data",
        "mode": "paper",
    }


@app.get("/api/market-data/shadow-comparison")
def get_shadow_market_comparison():
    """Compare Binance Spot and Bitunix Futures without changing strategy inputs."""
    return shadow_market_comparison.compare()


@app.get("/api/bitunix/candles")
def get_bitunix_candles(
    interval: str = Query("5m"),
    limit: int = Query(100, ge=1, le=1000),
):
    try:
        result = bitunix_market_service.get_candles(
            interval=interval, limit=limit, closed_only=True, include_metadata=True
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except BitunixMarketDataError as error:
        raise _bitunix_market_data_http_error(error) from None
    return {
        "symbol": "SOL/USDT",
        "interval": interval,
        "source": "Bitunix Futures",
        "candles": [
            {
                "time": int(row[0] / 1000),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
            for row in result["candles"]
        ],
        "candles_requested": result["requested"],
        "candles_returned": result["returned"],
        "complete": result["complete"],
        "history_exhausted": result["history_exhausted"],
        "warning": None if result["complete"] else "Histórico incompleto: no se alcanzó el número de velas cerradas solicitado.",
        "mode": "paper",
    }
