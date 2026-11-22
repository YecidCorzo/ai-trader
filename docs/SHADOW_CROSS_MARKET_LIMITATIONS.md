# Límites de la comparación shadow Binance Spot / Bitunix Futures

> **Estado:** documentación de seguimiento del endpoint propuesto en el PR #135. Este documento no habilita trading ni cambia el proveedor de estrategias.

## Qué mide

El endpoint `GET /api/market-data/shadow-comparison` compara el precio de Binance Spot con el `LAST_PRICE` de Bitunix USDT-M Futures para SOL/USDT. El diferencial firmado se calcula así:

```text
(Bitunix Futures LAST_PRICE - Binance Spot price)
------------------------------------------------- × 10,000
             Binance Spot price
```

Un resultado positivo indica que el último precio de Futures está por encima del precio Spot observado; uno negativo indica que está por debajo. El umbral predeterminado de 50 bps es únicamente un umbral operativo de alerta.

## Interpretación y límites

Esta salida es una **observación cross-market**, no una comparación de instrumentos equivalentes ni una señal de arbitraje:

- Spot y Futures son mercados distintos. Pueden diferir por financiación, base del contrato, liquidez, spread, estructura del instrumento y condiciones de mercado.
- Bitunix aporta `LAST_PRICE`, no `MARK_PRICE`. El último precio negociado no debe tratarse como precio de marca, precio de liquidación ni referencia para stops.
- Los proveedores se consultan secuencialmente. La respuesta no contiene timestamps de origen sincronizados para cada cotización; `compared_at` identifica el momento de construcción de la respuesta, no demuestra simultaneidad de las dos observaciones.
- El umbral de 50 bps no está calibrado como rentabilidad neta: no descuenta comisiones, funding, spread, slippage, latencia, límites de tamaño ni riesgo de ejecución.
- La caché de cinco segundos reduce llamadas repetidas, pero no convierte las cotizaciones en una muestra sincronizada ni garantiza que sigan siendo ejecutables.

Por tanto, no se debe interpretar `alert=true` como oportunidad de compra/venta, arbitraje rentable o instrucción para abrir una posición.

## Límites de seguridad y arquitectura

- Binance sigue siendo la fuente actual de la estrategia.
- Bitunix se usa aquí únicamente como fuente pública y de solo lectura.
- La comparación no modifica señales, backtests, sizing, stops, riesgo ni equity PAPER.
- No se usan endpoints privados, cuentas, posiciones, apalancamiento ni órdenes.
- No se habilita DEMO/TESTNET ni LIVE; no se usan credenciales ni fondos reales.

## Comprobación manual después de integrar el PR #135

1. Confirmar que ambos proveedores devuelven precios positivos y finitos.
2. Confirmar que un proveedor no disponible o con precio inválido produce `status=unavailable`, `basis_bps=null` y no genera una alerta numérica.
3. Confirmar que el umbral se aplica al valor absoluto del diferencial y que exactamente 50 bps no dispara la alerta predeterminada.
4. Verificar que el dashboard, señales, backtests y PAPER no consumen esta comparación como entrada de trading.

La integración solo debe considerarse una herramienta de observabilidad. Cualquier uso futuro en análisis o ejecución requiere un diseño y validación independientes, con precios comparables y timestamps de origen verificables.
