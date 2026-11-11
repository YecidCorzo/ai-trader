# AI Trader — estado de integración y preparación para pruebas

Fecha de revisión: 2026-11-11  
Rama inspeccionada: `trading/paper-execution-gate`  
Repositorio: `YecidCorzo/ai-trader`

## Decisión

**NO-GO para aceptación del usuario.** Esta rama de integración contiene avances funcionales y sus PR apilados tienen CI verde, pero no constituye todavía una versión candidata integrada en `feature/financial-platform`, ni una plataforma completa con todos los dominios previstos.

No debe confundirse el éxito de CI de cada PR con una validación end-to-end del producto integrado.

## Cadena de PR y evidencia de CI

Los siguientes PR están abiertos y forman una cadena de ramas:

| PR | Base → head | Alcance | CI observado |
|---|---|---|---|
| #38 | `finance/monthly-budgets` → `finance/repository-layer` | Repository pattern de finanzas | SUCCESS — 124 tests |
| #39 | `finance/repository-layer` → `trading/paper-ledger-risk-controls` | Ledger PAPER, riesgo y circuit breaker | SUCCESS — 132 tests |
| #40 | `trading/paper-ledger-risk-controls` → `trading/paper-execution-gate` | Gate previo a entrada PAPER | SUCCESS — 138 tests |

Los logs de GitHub Actions muestran en los tres casos: instalación desde `requirements.txt`, `pip check`, compilación con `compileall` y ejecución de `unittest`. Los conteos corresponden a cada head de PR; no se deben sumar como si fueran tres suites independientes ni presentarlos como una única ejecución final.

La rama `feature/financial-platform` sigue siendo divergente: la comparación consultada la situó 8 commits por delante y 147 por detrás de `main`. La rama superior de la cadena de PR también diverge de `feature/financial-platform`. La integración debe hacerse mediante revisión y PRs, nunca escribiendo directamente en `main` ni en `feature/financial-platform`.

## Implementado en esta cadena de ramas

- Manifiesto raíz `requirements.txt` con versiones fijadas para FastAPI, Requests y Uvicorn.
- CI con instalación, `pip check`, compilación y tests estándar de Python.
- Infraestructura SQLite con ruta configurable por `AI_TRADER_DB_PATH`, claves foráneas, timeout y migraciones SQL versionadas.
- API de finanzas personales para monedas, cuentas, categorías y transacciones manuales.
- Saldos iniciales, balances calculados, cash-flow e informes por moneda original.
- Presupuestos mensuales por categoría.
- `FinanceRepository` como frontera de persistencia para consultas SQL de finanzas.
- Ledger persistente de operaciones simuladas LONG/SHORT, P&L decimal y eventos de auditoría.
- Motor determinista de riesgo y circuit breaker persistente.
- `PaperExecutionService` que valida una entrada simulada antes de registrarla.

## No implementado o no integrado todavía

- Interfaz frontend completa para finanzas personales; los endpoints se exploran actualmente mediante Swagger en `/docs`.
- Importación CSV y detección de duplicados de extractos bancarios.
- Conversión FX y consolidación de patrimonio en SEK.
- Cartera de acciones/ETF/cripto con posiciones, valoración y rendimiento.
- Market Intelligence con noticias, macro, eventos y alertas.
- Un flujo completo de ejecución PAPER conectado desde señales de estrategia hasta el ledger y el dashboard.
- Un watcher de mercado que supervise y ejecute stops/targets.
- Derivación automática y verificada de equity, P&L diario, número de operaciones y rachas desde una cuenta PAPER completa.
- Pruebas end-to-end de instalación limpia, frontend y flujos completos de usuario en macOS.

## Limitaciones de seguridad y contabilidad

- Finanzas es local y single-user; no existe autenticación ni aislamiento por usuario. No exponer a LAN, internet, túneles ni reverse proxies.
- No hay integración bancaria, credenciales de exchange ni movimiento de dinero.
- Los importes se guardan en unidades menores enteras y la moneda original se conserva; no se aplican conversiones FX en informes actuales.
- El gate PAPER recibe un snapshot de riesgo del caller. No se debe enviar un snapshot vacío, antiguo o no verificado.
- El stop de una operación es metadato de riesgo y no una orden de stop ejecutada por un monitor.
- La estrategia no está certificada como rentable. Los resultados de backtest son simulaciones históricas y no garantías ni pronósticos.
- El dashboard de trading conserva un balance demo fijo de 10.000 USDT y una lista de posiciones vacía; no representa una cuenta persistente.

## Próximas puertas de calidad

1. Revisar los PR #38–#40 y su cadena de dependencias; resolver comentarios y cualquier conflicto antes de integrar.
2. Integrar la cadena en una rama candidata aislada mediante PR, sin commits directos a `main` ni a `feature/financial-platform`.
3. Ejecutar una única suite completa sobre el commit integrado y conservar logs y conteos exactos.
4. Añadir pruebas API para repository, ledger, gate PAPER y migraciones sobre una base SQLite temporal.
5. Verificar instalación limpia y arranque en macOS siguiendo el README.
6. Completar o reducir explícitamente el alcance de la primera versión visual; no declarar completos los dominios que solo tienen API parcial.
7. Mantener un checklist de aceptación y publicar limitaciones visibles antes de invitar al usuario a probar.

