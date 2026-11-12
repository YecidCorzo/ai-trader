# AI Trader — Financial Intelligence Platform

Plataforma local de análisis financiero y trading simulado. La versión actual combina un dashboard de mercado SOL/USDT con una API inicial de finanzas personales y servicios de investigación de trading.

> **Modo obligatorio: PAPER.** No envía órdenes reales, no conecta con cuentas de exchange ni mueve dinero.

## Requisitos

- macOS con Python 3.11 recomendado (es la versión utilizada por CI).
- Git.
- Conexión a internet para descargar dependencias, consultar datos públicos de Binance y cargar Lightweight Charts desde su CDN.

## Instalación en macOS

Desde Terminal, clona el repositorio y entra en el proyecto:

```bash
git clone https://github.com/YecidCorzo/ai-trader.git
cd ai-trader
```

Para probar el trabajo financiero en revisión, cambia a la rama `trading/paper-execution-gate`. No uses `main` ni `feature/financial-platform` como ramas de trabajo:

```bash
git fetch origin
git switch trading/paper-execution-gate
git pull
```

Crea y activa un entorno virtual:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

Si tu Mac no tiene el comando `python3.11`, instala Python 3.11 desde python.org o Homebrew y repite los comandos. No instales dependencias globalmente.

## Arranque

Desde la raíz del repositorio, con `.venv` activado:

```bash
uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Al iniciar, FastAPI aplica las migraciones SQLite pendientes. Por defecto, la base de datos se crea en `data/ai_trader.sqlite3`; ese directorio y los archivos de base de datos están excluidos de Git.

Abre:

- Dashboard: http://127.0.0.1:8000/dashboard
- Documentación interactiva de API: http://127.0.0.1:8000/docs
- Estado: http://127.0.0.1:8000/health

Para detener el servidor, vuelve a Terminal y pulsa `Ctrl+C`.

### Ubicación alternativa de la base de datos

Puedes definir `AI_TRADER_DB_PATH` antes de arrancar:

```bash
export AI_TRADER_DB_PATH="$HOME/ai-trader-data/ai_trader.sqlite3"
uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Haz una copia de seguridad del archivo SQLite antes de actualizar o probar migraciones.

## Ejecutar las pruebas

En otra ventana de Terminal, desde la raíz del repositorio y con el entorno virtual activado:

```bash
python -m pip check
python -m compileall -q backend tests
PYTHONPATH=backend python -m unittest discover -s tests -v
```

La suite usa `unittest` de la biblioteca estándar de Python; no hace falta instalar pytest.

## Qué incluye esta rama de integración

- Datos públicos de mercado Binance para SOL/USDT, indicadores y señales.
- Backtesting e investigación walk-forward/estadística.
- API inicial de finanzas personales: monedas, cuentas, categorías, transacciones, saldos iniciales, presupuestos mensuales e informes de cash flow.
- Persistencia local SQLite con migraciones versionadas y repositorio de finanzas.
- Ledger PAPER de operaciones simuladas, eventos de auditoría, motor de riesgo y circuit breaker.
- Servicio de validación previa para entradas PAPER.

La API financiera se puede explorar desde `/docs`. El dashboard visual actual sigue centrado en trading; todavía no ofrece una interfaz completa de finanzas personales, cartera de inversiones o inteligencia de mercado.

## Límites y seguridad importantes

- La API financiera es local y de un solo usuario, sin autenticación. **No expongas el servidor a la LAN, internet, túneles ni reverse proxies.** Mantén el bind en `127.0.0.1`.
- No hay conexión bancaria, importación CSV, conversión FX automática ni movimiento de dinero.
- Los valores financieros se conservan por moneda original; los informes no convierten ni mezclan monedas.
- El servicio de ejecución PAPER registra precios/fills simulados proporcionados por el caller. No consulta el mercado para ejecutar ni envía órdenes.
- El estado de equity, P&L diario y contadores de riesgo todavía depende de snapshots verificados suministrados por el caller; no se deriva automáticamente de una curva de capital completa.
- El stop se guarda como metadato de riesgo; no hay un watcher de mercado que lo ejecute.
- No hay evidencia de una estrategia rentable. Los backtests son simulaciones y no predicen resultados.
- La interfaz de trading muestra un balance demo fijo y posiciones vacías; no son datos de una cuenta real ni del ledger persistente.

Consulta [docs/PLATFORM_STATUS.md](docs/PLATFORM_STATUS.md) para el estado de integración y las limitaciones verificadas. Consulta [docs/PERSONAL_FINANCE_SECURITY.md](docs/PERSONAL_FINANCE_SECURITY.md) y [docs/PAPER_TRADING_CONTROLS.md](docs/PAPER_TRADING_CONTROLS.md) antes de usar los módulos financieros o PAPER.
