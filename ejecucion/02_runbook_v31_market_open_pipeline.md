# Runbook V31 Market Open Pipeline

## Objetivo

Validar que Stock Ultimus V31 reciba datos frescos desde el entorno local y deje de mostrar `NO_DATA` o `NO_MASTER_SNAPSHOT` en produccion.

Este flujo es decision support solamente. No coloca ordenes, no autoriza ejecucion y no cambia el principio de revision manual.

## Precondiciones

- TWS o IB Gateway abierto y conectado.
- Cuenta IBKR disponible para datos de mercado.
- TradingView con alertas QQQ/SPY activas si se va a validar contexto tecnico intradia.
- Render desplegado con endpoints V31 disponibles.
- Repo local ubicado en:

```bash
cd /Users/ernestomagana04/Projects/trading-engine
```

Confirmar Render:

```bash
curl -sS https://trading-engine-p097.onrender.com/v31_data_pipeline_status
curl -sS https://trading-engine-p097.onrender.com/v31_monitor_notify/preview
```

Estado esperado antes de publicar datos:

- `status`: `NO_MASTER_SNAPSHOT`
- `canonical_ingest`: `/v31_ingest_snapshot`
- `master_snapshot_available`: `false`
- `preview.email_sent`: `false`
- `preview.not_order_instruction`: `true`

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

## Paso 3. Correr bridge local durante mercado

Con IBKR abierto:

```bash
python3 ibkr_bridge.py
```

Esperar a que el bridge genere ciclo nuevo y runtime fresco.

Senales positivas en consola:

- IBKR conectado correctamente.
- Se generan filas de opciones.
- Se actualizan snapshots runtime.
- Aparece publicacion hacia V31:

```text
V28.3 OFFICIAL V31 SNAPSHOT PUBLISHED | ok:True | status:200 | rows:... | technical:... | url:https://trading-engine-p097.onrender.com/v31_ingest_snapshot
```

Si el bridge falla antes de generar runtime, detener y revisar conexion IBKR antes de continuar.

## Paso 4. Validar pipeline remoto despues del primer ciclo

```bash
curl -sS https://trading-engine-p097.onrender.com/v31_data_pipeline_status
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

## Paso 5. Validar frescura local como respaldo

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

## Paso 6. Publicar snapshot V31 manualmente solo como respaldo

El camino principal es la autopublicacion del bridge. Usar este paso solo si el bridge genero runtime fresco pero no logro publicar a Render.

Solo cuando el dry-run indique `stale: false`:

```bash
python3 tools/publish_v31_snapshot_from_runtime.py --publish
```

Resultado esperado:

- `publish_result.ok`: `true`
- `status_code`: `200`
- target: `https://trading-engine-p097.onrender.com/v31_ingest_snapshot`

## Paso 7. Validar decisiones V31

Ejemplos:

```bash
curl -sS https://trading-engine-p097.onrender.com/gpt_v31_trade_decision/QQQ
curl -sS https://trading-engine-p097.onrender.com/gpt_v31_trade_decision/SPY
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

## Paso 8. Revisar monitor V31

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

## Paso 9. Revisar dashboard

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
- [ ] Repo en `/Users/ernestomagana04/Projects/trading-engine`.
- [ ] Render responde `/v31_data_pipeline_status`.
- [ ] Bridge apunta a `/v31_ingest_snapshot`.
- [ ] TradingView QQQ/SPY alertas activas si aplica.
- [ ] Ejecutar `python3 ibkr_bridge.py`.
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
curl -sS https://trading-engine-p097.onrender.com/v31_data_pipeline_status
curl -sS https://trading-engine-p097.onrender.com/v31_monitor_status
curl -sS https://trading-engine-p097.onrender.com/v31_monitor_notify/preview
python3 tools/publish_v31_snapshot_from_runtime.py
python3 tools/publish_v31_snapshot_from_runtime.py --publish
curl -sS https://trading-engine-p097.onrender.com/gpt_v31_trade_decision/QQQ
```
