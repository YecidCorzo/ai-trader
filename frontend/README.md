# AI Trader — frontend

Dashboard web servido por FastAPI en `/dashboard`.

## Funciones disponibles

- Precio público SOL/USDT consultado desde la API del backend.
- Gráfico de velas SOL/USDT.
- Consulta de análisis técnico avanzado mediante `GET /api/signal/v2`.
- Confirmación multi-timeframe 1h/4h mediante `GET /api/signal/multi-timeframe`, con consenso estricto: LONG o SHORT solo cuando ambos intervalos coinciden; discrepancias o datos incompletos producen NEUTRAL.
- Visualización por intervalo de EMA 9/21/50, RSI, MACD, VWAP, ATR, puntuación de reglas, niveles de entrada/salida e invalidación cuando están disponibles.
- Presentación de señal LONG/SHORT/NEUTRAL, puntuación, entrada de referencia, stop loss, take profits, invalidación y motivos.
- Backtest histórico PAPER y validación walk-forward PAPER.

## Ejecutar localmente en macOS

Desde la raíz del repositorio, crea el entorno virtual (solo la primera vez) e instala las dependencias:

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

Arranca FastAPI desde `backend` usando ese mismo intérprete:

```sh
cd backend
../.venv/bin/python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Abre:

```
http://127.0.0.1:8000/dashboard/
```

El frontend usa rutas relativas (`/api/...`) para comunicarse con la misma instancia de FastAPI. No abras `index.html` directamente con `file://`.

## Límite actual de integración PAPER

El panel de análisis es de solo lectura. Consultar una señal no abre ni cierra operaciones. El saldo del dashboard general permanece sin configurar porque `/api/dashboard` es un placeholder deliberado; la interfaz no inventa capital ni posiciones.

La API persistente `/api/paper/*` requiere un proveedor OIDC real configurado en el backend y un token Bearer válido. Esta interfaz todavía no implementa inicio de sesión OIDC ni gestión autenticada de cuentas PAPER. Consulta `docs/PAPER_API_OIDC_SETUP.md` para la configuración y las pruebas de aceptación de la API. La secuencia completa de aceptación de release está en `docs/PAPER_RELEASE_ACCEPTANCE.md`.

## Seguridad

- Solo modo PAPER.
- Sin credenciales de exchange, órdenes reales ni endpoints live.
- No introduzcas tokens, secretos ni claves privadas en el código del frontend.
