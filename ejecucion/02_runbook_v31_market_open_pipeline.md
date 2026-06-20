# Runbook V31 Market Open Pipeline

## Objetivo

Validar que Stock Ultimus V31 reciba datos frescos desde el entorno local y deje de mostrar `NO_DATA` o `NO_MASTER_SNAPSHOT` en produccion.

Este flujo es decision support solamente. No coloca ordenes, no autoriza ejecucion y no cambia el principio de revision manual.

## Precondiciones

- TWS o IB Gateway abierto y conectado.
- Cuenta IBKR disponible para datos de mercado.
- TradingView con alertas QQQ/SPY activas si se va a validar contexto tecnico intradia.
- Render desplegado con endpoints V31 disponibles.
- `READ_ACCESS_TOKEN` disponible localmente para endpoints de lectura protegidos.
- Repo local ubicado en:

```bash
cd /private/tmp/stock-ultimus-p0
```

> Si se trabaja desde otro clon, confirmar que `git status --short --branch`
> muestra `main...origin/main` y que contiene `tools/v31_operational_check.py`.

Confirmar Render:

```bash
READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)" \
python3 tools/v31_operational_check.py --ticker SPY

READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)"
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" \
  https://trading-engine-p097.onrender.com/v31_data_pipeline_status
```

Estado esperado antes de publicar datos:

- `status`: `NO_MASTER_SNAPSHOT` u `OK` con snapshot previo
- `canonical_ingest`: `/v31_ingest_snapshot`
- `preview.email_sent`: `false`
- `preview.not_order_instruction`: `true`
- `v31_operational_check.ok`: `true`

## Paso 1. Revisar target activo del bridge

El hook activo del bridge debe publicar a V31 por default.

```bash
rg -n "TRADING_ENGINE_INGEST_PATH|_V283_INGEST_URL|v31_ingest_snapshot|OFFICIAL V31" ibkr_bridge.py
```

Confirmar:

- default `TRADING_ENGINE_INGEST_PATH`: `/v31_ingest_snapshot`
- log esperado: `V28.3 OFFICIAL V31 SNAPSHOT PUBLISHED`
- URL esperada: `https://trading-engine-p097.onrender.com/v31_ingest_snapshot`

No exportar `TRADING_ENGINE_INGEST_PATH=/v28_ingest_snapshot` durante operacion normal.

## Paso 2. Revisar que no se publique snapshot viejo

Ejecutar dry-run:

```bash
python3 tools/publish_v31_snapshot_from_runtime.py
```

Si devuelve:

- `stale: true`
- `rows_found > 0`
- `technical_count > 0`

entonces hay datos historicos en `runtime/`, pero no deben publicarse a produccion.

No usar `--allow-stale` salvo prueba historica explicita.

## Paso 3. Diagnosticar quote de opcion antes del bridge completo

Primero aislar IBKR option market data con una sola opcion. Esto no publica a
Render y no coloca ordenes.

Auto-seleccion de contrato SPY put cercano a 45 DTE y 10% OTM:

```bash
python3 tools/ibkr_option_quote_probe.py \
  --ticker SPY \
  --right P \
  --target-dte 45 \
  --otm-pct 0.10
```

Resultado util:

- `readonly`: `true`
- `not_order_instruction`: `true`
- `best.data_quality`: idealmente `FULL_WITH_GREEKS`
- `best.bid`, `best.ask`, `best.mid`, `best.spread`, `best.spread_pct`, `best.greeks.delta` presentes
- `best.source` indica si gano `STREAM_TYPE_1`, `SNAPSHOT_TYPE_1`, `STREAM_TYPE_2`, etc.

Si no hay `bid/ask`:

- revisar errores IBKR en `errors`
- verificar permisos de opciones en TWS/IBKR
- probar si TWS muestra bid/ask para el contrato elegido
- no continuar esperando `ENTRY_READY`; el sistema debe quedar en `WAIT_OPTIONS_DATA`

## Paso 4. Correr bridge local durante mercado

Con IBKR abierto:

```bash
TRADING_ENGINE_INGEST_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-snapshot-ingest -w)" \
IBKR_PORT=7496 \
IBKR_MARKET_DATA_TYPE=1 \
IBKR_WATCHLIST=SPY \
IBKR_OPTION_SYMBOLS=SPY \
PYTHONUNBUFFERED=1 \
python3 ibkr_bridge.py --once
```

Esperar a que el bridge genere ciclo nuevo y runtime fresco.

Senales positivas en consola:

- IBKR conectado correctamente.
- Se generan filas de opciones.
- Se actualizan snapshots runtime.
- `option_source:` muestra que fuente de market data de opcion gano.
- Aparece publicacion hacia V31:

```text
V28.3 OFFICIAL V31 SNAPSHOT PUBLISHED | ok:True | status:200 | rows:... | technical:... | url:https://trading-engine-p097.onrender.com/v31_ingest_snapshot
```

Si el bridge falla antes de generar runtime, detener y revisar conexion IBKR antes de continuar.

## Paso 5. Ejecutar compuerta operacional V31

```bash
TRADING_ENGINE_INGEST_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-snapshot-ingest -w)" \
python3 tools/v31_operational_check.py \
  --ticker SPY \
  --run-bridge \
  --require-open-data \
  --min-rows 1
```

Resultado esperado:

- `ok`: `true`
- `bridge_once_completed`: `true`
- `pipeline.rows_found >= 1`
- `decision.final_state` distinto de `NO_DATA`
- `decision.not_order_instruction`: `true`
- `decision.can_operate`: `false`

Si falla `rows_found_minimum` o `decision_not_no_data`, revisar primero
`tools/ibkr_option_quote_probe.py`.

## Paso 6. Validar pipeline remoto despues del primer ciclo

```bash
READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)"
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" \
  https://trading-engine-p097.onrender.com/v31_data_pipeline_status
```

Resultado esperado:

- `status`: `OK`
- `master_snapshot_available`: `true`
- `rows_found > 0`
- `master_source`: `runtime/v28_master_snapshot.json` o `runtime/v25_master_snapshot.json`

Si aun aparece `NO_MASTER_SNAPSHOT`, revisar la consola del bridge:

- URL publicada.
- `ok:true`.
- `status:200`.
- cantidad de `rows`.
- errores de red.

## Paso 7. Validar frescura local como respaldo

En otra terminal:

```bash
python3 tools/publish_v31_snapshot_from_runtime.py
```

Condiciones minimas:

- `stale: false`
- `rows_found > 0`
- `runtime_files_seen` contiene archivos actualizados
- `tickers_detected` contiene tickers esperados

Si `stale` sigue en `true`, no publicar.

## Paso 8. Publicar snapshot V31 manualmente solo como respaldo

El camino principal es la autopublicacion del bridge. Usar este paso solo si el bridge genero runtime fresco pero no logro publicar a Render.

Solo cuando el dry-run indique `stale: false`:

```bash
TRADING_ENGINE_INGEST_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-snapshot-ingest -w)" \
python3 tools/publish_v31_snapshot_from_runtime.py --publish
```

Resultado esperado:

- `publish_result.ok`: `true`
- `status_code`: `200`
- target: `https://trading-engine-p097.onrender.com/v31_ingest_snapshot`

## Paso 9. Validar decisiones V31

Ejemplos:

```bash
READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)"
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" \
  https://trading-engine-p097.onrender.com/gpt_v31_trade_decision/QQQ

READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)"
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" \
  https://trading-engine-p097.onrender.com/gpt_v31_trade_decision/SPY
```

Estados esperados posibles:

- `WAIT_MARKET`
- `WAIT_OPTIONS_DATA`
- `WAIT_TECHNICAL`
- `RISK_BLOCKED`
- `MANUAL_REVIEW`
- `ENTRY_READY`

Estado no deseado si ya hay snapshot fresco:

- `NO_DATA`

Si sigue `NO_DATA`, revisar:

- `rows_found`
- `technical_count`
- `runtime_files`
- `required_missing_fields`
- `master_source`

## Paso 10. Revisar monitor V31

```bash
curl -sS https://trading-engine-p097.onrender.com/v31_monitor_status
curl -sS https://trading-engine-p097.onrender.com/v31_monitor_notify/preview
```

Interpretacion:

- `INFO`: no hay accion inmediata.
- `WARNING`: hay blockers o datos incompletos; revisar antes de cualquier decision.
- `ACTION_REQUIRED`: hay setup listo para revision manual o pipeline caido durante mercado.
- `email_sent:false` en preview es correcto.
- Si Resend sigue sin cuota, `POST /v31_monitor_notify` puede devolver `not_sent`; eso no invalida el motor.

No usar `force=true` durante mercado salvo prueba explicita de canal de correo.

## Paso 11. Revisar dashboard

Abrir:

```text
https://trading-engine-p097.onrender.com/v31_dashboard
```

Confirmar:

- V31 muestra tickers.
- `Can Operate` sigue en `0`.
- `Manual Ready` solo cuenta setups listos para revision manual.
- Blockers son explicitos.

## Checklist rapido de market open

- [ ] TWS/IB Gateway abierto y conectado.
- [ ] Repo en `/private/tmp/stock-ultimus-p0` o clon equivalente en `main`.
- [ ] Render responde `/v31_data_pipeline_status`.
- [ ] Bridge apunta a `/v31_ingest_snapshot`.
- [ ] TradingView QQQ/SPY alertas activas si aplica.
- [ ] Ejecutar `python3 tools/ibkr_option_quote_probe.py --ticker SPY --right P --target-dte 45 --otm-pct 0.10`.
- [ ] Confirmar si hay `bid/ask/spread/spread_pct/delta`.
- [ ] Ejecutar `python3 tools/v31_operational_check.py --ticker SPY --run-bridge --require-open-data --min-rows 1`.
- [ ] Ver log `V28.3 OFFICIAL V31 SNAPSHOT PUBLISHED`.
- [ ] Confirmar `status: OK` en `/v31_data_pipeline_status`.
- [ ] Confirmar `rows_found > 0`.
- [ ] Revisar `/v31_monitor_status`.
- [ ] Revisar `/v31_dashboard`.
- [ ] No operar automaticamente; todo setup es revision manual.

## Criterios de exito

- `v31_data_pipeline_status.status` pasa a `OK`.
- `v31_system_status.master_snapshot_available` es `true`.
- `rows_found > 0`.
- Por lo menos un ticker deja `NO_DATA`.
- `can_operate` permanece `false` o `0`.
- Todo `ENTRY_READY` sigue marcado como revision manual, no ejecucion.

## Reglas de seguridad

- No publicar snapshots viejos.
- No usar `--allow-stale` para produccion.
- No ejecutar ordenes desde el sistema.
- No tratar `ENTRY_READY` como permiso de operar.
- No cambiar `can_operate:false`.
- Si faltan campos de contrato, mantener `WAIT_OPTIONS_DATA`.
- No forzar email durante mercado salvo prueba deliberada.

## Comandos rapidos

```bash
cd /Users/ernestomagana04/Projects/trading-engine
rg -n "TRADING_ENGINE_INGEST_PATH|_V283_INGEST_URL|v31_ingest_snapshot|OFFICIAL V31" ibkr_bridge.py
python3 ibkr_bridge.py
READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)" python3 tools/v31_operational_check.py --ticker SPY
python3 tools/publish_v31_snapshot_from_runtime.py
python3 tools/publish_v31_snapshot_from_runtime.py --publish
READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)"
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" https://trading-engine-p097.onrender.com/gpt_v31_trade_decision/QQQ
```
