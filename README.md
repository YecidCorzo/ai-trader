# AI Trader — crypto trading

Plataforma de análisis de mercado cripto con datos públicos reales, señales técnicas explicables, backtesting y simulación interna PAPER.

> **Estado del release: BLOCKED.** Este repositorio todavía no tiene una aceptación de release completa. No presentes esta versión como lista para operar ni como una estrategia rentable.

## Alcance y límites de seguridad

- **Mercado:** Binance se utiliza únicamente para consultar datos públicos de mercado en modo lectura.
- **Análisis:** señales e indicadores técnicos; una señal NEUTRAL también es un resultado válido.
- **PAPER:** ledger interno con capital ficticio. No representa saldo de un exchange.
- **Ejecución externa:** no se incluye un adaptador de órdenes DEMO/TESTNET verificado.
- **LIVE:** prohibido en este release. No se admiten credenciales de exchange, órdenes live, fondos reales ni endpoints live.

El dashboard de análisis es de solo lectura. Consultar una señal no abre ni cierra una operación. El dashboard todavía no implementa inicio de sesión OIDC ni gestión autenticada de cuentas PAPER.

## Requisitos

- Python 3.11 (misma versión principal utilizada por CI).
- macOS/Linux con un entorno virtual de Python.
- Conexión a Internet para consultar los datos públicos de mercado.

## Instalación rápida (backend + dashboard)

Desde la raíz del repositorio:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
PYTHONPATH=backend python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Abre:

- Dashboard: http://127.0.0.1:8000/dashboard/
- API y Swagger: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

No abras el HTML directamente con `file://`: el dashboard utiliza rutas relativas servidas por la misma instancia de FastAPI.

En macOS, la guía del frontend también documenta la creación del entorno virtual y el arranque desde `backend`: [frontend/README.md](frontend/README.md).

## PAPER API: configuración adicional obligatoria

La API persistente `/api/paper/*` está protegida por OIDC y falla de forma cerrada si falta configuración. Ya se completó un smoke test local con Keycloak 26.8.2, realm `ai-trader`, PKCE S256 y acceso autenticado a la API (HTTP 200) el 17-11-2026. Para aceptar el release aún hacen falta pruebas con dos identidades, rotación/fallos de JWKS, política de revocación y recorrido completo PAPER en el entorno controlado.

Sigue la guía completa antes de llamar a las rutas PAPER:

- [Configuración de API PAPER y OIDC](docs/PAPER_API_OIDC_SETUP.md)
- [Límite de autenticación y propiedad de cuentas](docs/PAPER_AUTHORIZATION_BOUNDARY.md)
- [Procedimiento de aceptación PAPER](docs/PAPER_RELEASE_ACCEPTANCE.md)

No hay un emisor local de tokens. No inventes ni compartas secretos, tokens o claves en el repositorio, issues, PRs o logs. Usa exclusivamente capital ficticio en una base de datos de pruebas persistente.

## Pruebas y evidencia

Las dependencias de desarrollo están fijadas en `requirements-dev.txt`. La evidencia de pruebas automatizadas debe consultarse en GitHub Actions para el commit o PR concreto. Un workflow verde no sustituye la aceptación con un proveedor OIDC externo.

La aceptación del release solo es PASS cuando se completan y revisan todos los checks aplicables de `docs/PAPER_RELEASE_ACCEPTANCE.md`. Si no se han ejecutado, deben permanecer pendientes; no se deben marcar como superados por inferencia.

## Limitaciones conocidas

- No hay integración de órdenes de exchange DEMO/TESTNET.
- No hay ejecución LIVE ni se permite añadirla a este release.
- El dashboard no implementa login OIDC ni administración autenticada de cuentas PAPER.
- El smoke test Keycloak + PKCE ya está realizado; siguen pendientes la aceptación con dos identidades, rotación/fallos de TLS/JWKS, política de revocación/sesión y pruebas end-to-end de PAPER.
- El dashboard no implementa todavía login OIDC ni administración autenticada de cuentas PAPER.
- El monitoreo de stops es por polling y no garantiza ejecución durante gaps o caídas del proveedor, worker o base de datos.
- Un backtest o una señal no demuestra rentabilidad futura. Consulta los artefactos de aceptación histórica y conserva visibles los resultados negativos.

## Política de cambios

Trabaja desde `main` mediante ramas de trabajo y pull requests. No hagas commits directamente en `main` ni utilices `feature/financial-platform` como línea de integración. No declares una plataforma compatible sin un adaptador implementado y pruebas satisfactorias.
