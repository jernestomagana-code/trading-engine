# Runbook V31 Market Open Pipeline

## Objetivo

Validar que Stock Ultimus V31 reciba datos frescos desde el entorno local y deje de mostrar `NO_DATA` en produccion.

Este flujo es decision support solamente. No coloca ordenes, no autoriza ejecucion y no cambia el principio de revision manual.

## Precondiciones

- TWS o IB Gateway abierto y conectado.
- Cuenta IBKR disponible para datos de mercado.
- Repo local ubicado en:

```bash
cd /Users/ernestomagana04/Projects/trading-engine
```

- Render activo:

```bash
curl -sS https://trading-engine-p097.onrender.com/v31_data_pipeline_status
```

Estado esperado antes de publicar datos:

- `status`: `NO_MASTER_SNAPSHOT`
- `canonical_ingest`: `/v31_ingest_snapshot`
- `master_snapshot_available`: `false`

## Paso 1. Revisar que no se publique snapshot viejo

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

## Paso 2. Correr bridge local durante mercado

Con IBKR abierto:

```bash
python3 ibkr_bridge.py
```

Esperar a que el bridge genere ciclo nuevo y runtime fresco.

Senales positivas en consola:

- IBKR conectado correctamente.
- Se generan filas de opciones.
- Se actualizan snapshots runtime.
- Aparece publicacion hacia V31 o URL `/v31_ingest_snapshot`.

Si el bridge falla antes de generar runtime, detener y revisar conexion IBKR antes de continuar.

## Paso 3. Validar frescura local

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

## Paso 4. Publicar snapshot V31

Solo cuando el dry-run indique `stale: false`:

```bash
python3 tools/publish_v31_snapshot_from_runtime.py --publish
```

Resultado esperado:

- `publish_result.ok: true`
- `status_code`: `200`
- target: `https://trading-engine-p097.onrender.com/v31_ingest_snapshot`

## Paso 5. Validar pipeline remoto

```bash
curl -sS https://trading-engine-p097.onrender.com/v31_data_pipeline_status
```

Resultado esperado:

- `status`: `OK`
- `master_snapshot_available`: `true`
- `rows_found > 0`
- `master_source`: `runtime/v28_master_snapshot.json` o `runtime/v25_master_snapshot.json`

## Paso 6. Validar decisiones V31

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

## Paso 7. Revisar dashboard

Abrir:

```text
https://trading-engine-p097.onrender.com/v31_dashboard
```

Confirmar:

- V31 muestra tickers.
- `Can Operate` sigue en `0`.
- `Manual Ready` solo cuenta setups listos para revision manual.
- Blockers son explicitos.

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

## Comandos rapidos

```bash
cd /Users/ernestomagana04/Projects/trading-engine
python3 tools/publish_v31_snapshot_from_runtime.py
python3 tools/publish_v31_snapshot_from_runtime.py --publish
curl -sS https://trading-engine-p097.onrender.com/v31_data_pipeline_status
curl -sS https://trading-engine-p097.onrender.com/gpt_v31_trade_decision/QQQ
```

