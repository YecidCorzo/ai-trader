# Repository Instructions

## Project structure
- `backend/main.py` defines the FastAPI app and API routes.
- `backend/indicators/`, `backend/strategies/`, and `backend/services/` contain indicator calculations, trading strategies, and market/backtest services.
- `frontend/index.html` is a standalone HTML/CSS/JavaScript dashboard, served by FastAPI at `/dashboard`.
- The dashboard and API currently use SOL/USDT and paper-trading mode. Keep changes paper-only unless the user explicitly requests otherwise.

## Development
- Start the backend from `backend/` with `.venv/bin/uvicorn main:app --reload`.
- Open the dashboard at `http://127.0.0.1:8000/dashboard`.
- Market data is fetched from Binance by `backend/services/market_services.py`; avoid relying on live network data in local checks.
- No dependency manifest or test suite is currently present. Do not assume additional packages or test commands without checking the repository.

## Change conventions
- Keep API response shapes and the existing module boundaries stable unless the task requires changing them.
- The dashboard's user-facing text is Spanish; preserve that language for new UI text.
- Keep changes focused and do not edit generated files, virtual environments, or `*.save` backups.