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

## Camino recomendado. Runner unico de market open

Durante mercado abierto, correr primero el runner. Ejecuta el probe de opcion,
el bridge read-only y el operational check V31 en secuencia, sin imprimir
tokens ni colocar ordenes.

Dry-run seguro:

```bash
python3 tools/v31_market_open_runner.py --dry-run
```

Ejecucion real durante mercado:

```bash
python3 tools/v31_market_open_runner.py \
  --ticker SPY \
  --right P \
  --target-dte 45 \
  --otm-pct 0.10
```

Resultado esperado:

- `engine`: `V31_MARKET_OPEN_RUNNER`
- `ok`: `true`
- paso `ibkr_option_quote_probe`: `ok=true`
- paso `v31_operational_check`: `ok=true`
- `secrets_printed`: `false`
- `not_order_instruction`: `true`

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
  --min-rows 1 \
  --post-bridge-wait-seconds 60 \
  --post-bridge-poll-interval 5
```

Resultado esperado:

- `ok`: `true`
- `bridge_once_completed`: `true`
- `post_bridge_pipeline_ready`: `true`
- `pipeline.rows_found >= 1`
- `decision.final_state` distinto de `NO_DATA`
- `strategy_performance_ok`: `true`
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

## Paso 11. Validar regimen, playbook y recomendaciones diarias

```bash
READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)"
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" \
  https://trading-engine-p097.onrender.com/v31_daily_recommendations
```

Campos que deben aparecer:

- `strategy_playbook.registry_version`: `strategy_registry_v1`
- `strategy_regime_policy.parameter_matrix_available`: `true`
- `market.regime_detection.detector_version`: `market_regime_detector_v1`
- cada item debe incluir:
  - `strategy_overlay`
  - `regime_overlay`
  - `parameter_review`
  - `not_order_instruction: true`
  - `execution_authorized: false` dentro de overlays/reviews

Interpretacion de `market.market_regime`:

- `UNKNOWN`: aceptable antes de snapshot fresco o sin evidencia tecnica/mercado suficiente.
- `BULLISH_LOW_VOL`, `NEUTRAL_RANGE`, `BEARISH_OR_CORRECTION`, `HIGH_VOL_EVENT_RISK`, `INTRADAY_TREND`: regimen detectado o explicito.

Si `market_regime` sigue en `UNKNOWN` con mercado abierto y snapshot fresco:

- revisar `technical_count` en `/v31_data_pipeline_status`
- revisar que TradingView haya enviado score/trend/contexto reciente
- revisar si el snapshot trae `vix`, `atr_pct`, `adx`, `event_risk` o `market_regime`
- no forzar un regimen manual salvo que haya evidencia; `UNKNOWN` debe quedar conservador

Interpretacion de `parameter_review.status`:

- `PASS`: el setup cae dentro de los parametros esperados para su regimen y estrategia.
- `REVIEW_REQUIRED`: hay datos fuera de rango o faltantes; revisar blockers/missing_fields.
- `BLOCKED_BY_REGIME`: la estrategia no debe promoverse bajo ese regimen.
- `WAIT_OPTIONS_DATA`: no hay contrato ejecutable completo; no pasar a revision de entrada.
- `NO_GUIDANCE`: no hay matriz aplicable, normalmente por `UNKNOWN` o estrategia no cubierta.

## Paso 12. Validar tracking y performance de aprendizaje

```bash
READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)"
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" \
  https://trading-engine-p097.onrender.com/v31_outcome_tracking_status

curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" \
  https://trading-engine-p097.onrender.com/v32_strategy_performance
```

Resultado esperado:

- `v31_outcome_tracking_status.tracking_version`: `v31_entry_ready_signal_outcome_v1`
- `by_market_regime` presente
- `by_parameter_review_status` presente
- `v32_strategy_performance.strategy_performance_version`: `strategy_performance_v1`
- `summary.strategy_regime_group_count` presente
- `summary.parameter_review_group_count` presente
- `strategy_regime_performance` presente
- `parameter_review_performance` presente
- `execution_authorized`: `false`

Si hay `ENTRY_READY`, debe sembrarse un outcome pendiente de papel. Confirmar:

- `pending_entry_ready_signals` sube
- el recent signal contiene `market_regime`
- contiene `regime_overlay`
- contiene `parameter_review_status`
- contiene `selected_contract`

## Paso 13. Auto-evaluar outcomes pendientes

Usar primero `dry_run=true`. Esto no guarda cambios; solo valida si hay datos comparables en el snapshot actual.

```bash
READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)"
curl -sS -X POST -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" \
  "https://trading-engine-p097.onrender.com/v31_evaluate_pending_outcomes?dry_run=true&limit=25&checkpoint=EOD"
```

Resultado esperado:

- `engine`: `V31_PENDING_OUTCOME_AUTO_EVALUATION`
- `outcome_evaluation_version`: `v31_pending_outcome_auto_eval_v1`
- `dry_run`: `true`
- `not_order_instruction`: `true`
- `execution_authorized`: `false`

Si `evaluated_count > 0` y se quiere guardar la medicion de papel:

```bash
READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)"
curl -sS -X POST -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" \
  "https://trading-engine-p097.onrender.com/v31_evaluate_pending_outcomes?dry_run=false&limit=25&checkpoint=EOD"
```

La evaluacion calcula:

- `current_paper_pnl_r`
- `mfe_r`
- `mae_r`
- `latest_auto_evaluation`
- `auto_evaluations`

Si aparece `NOT_EVALUATED`, revisar `reason`:

- `CURRENT_OPTION_ROW_MISSING`: no hay fila actual comparable por ticker/estrategia/expiration/strike.
- `CURRENT_MID_MISSING`: la fila actual no trae mid/bid/ask.
- `ENTRY_MID_MISSING`: el outcome pendiente no guardo prima inicial.

No interpretar esta evaluacion como trade real. Es medicion de papel para aprendizaje.

## Paso 14. Revisar dashboard

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
- [ ] Ejecutar `python3 tools/v31_market_open_runner.py --dry-run`.
- [ ] Ejecutar `python3 tools/v31_market_open_runner.py --ticker SPY --right P --target-dte 45 --otm-pct 0.10`.
- [ ] Ejecutar `python3 tools/ibkr_option_quote_probe.py --ticker SPY --right P --target-dte 45 --otm-pct 0.10`.
- [ ] Confirmar si hay `bid/ask/spread/spread_pct/delta`.
- [ ] Ejecutar `python3 tools/v31_operational_check.py --ticker SPY --run-bridge --require-open-data --min-rows 1 --post-bridge-wait-seconds 60 --post-bridge-poll-interval 5`.
- [ ] Ver log `V28.3 OFFICIAL V31 SNAPSHOT PUBLISHED`.
- [ ] Confirmar `status: OK` en `/v31_data_pipeline_status`.
- [ ] Confirmar `rows_found > 0`.
- [ ] Revisar `/v31_daily_recommendations`.
- [ ] Confirmar `market.regime_detection.detector_version=market_regime_detector_v1`.
- [ ] Confirmar `strategy_regime_policy.parameter_matrix_available=true`.
- [ ] Confirmar que cada item tenga `regime_overlay` y `parameter_review`.
- [ ] Revisar `/v31_outcome_tracking_status`.
- [ ] Revisar `/v32_strategy_performance`.
- [ ] Si hay outcomes pendientes y snapshot posterior, correr `POST /v31_evaluate_pending_outcomes?dry_run=true`.
- [ ] Si el dry-run evalua correctamente, correr `dry_run=false` solo para guardar medicion de papel.
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
- `/v31_daily_recommendations` incluye regimen, matriz y revision de parametros.
- `/v31_outcome_tracking_status` agrupa por regimen y parameter review.
- `/v32_strategy_performance` expone performance por regimen y por `parameter_review_status`.
- `/v31_evaluate_pending_outcomes` responde en `dry_run` sin autorizar ejecucion.

## Reglas de seguridad

- No publicar snapshots viejos.
- No usar `--allow-stale` para produccion.
- No ejecutar ordenes desde el sistema.
- No tratar `ENTRY_READY` como permiso de operar.
- No cambiar `can_operate:false`.
- Si faltan campos de contrato, mantener `WAIT_OPTIONS_DATA`.
- No forzar email durante mercado salvo prueba deliberada.
- No convertir auto-evaluaciones de papel en resultados reales sin revision manual.
- No usar outcomes pendientes para relajar parametros sin muestra suficiente y cambio versionado.

## Comandos rapidos

```bash
cd /private/tmp/stock-ultimus-p0
rg -n "TRADING_ENGINE_INGEST_PATH|_V283_INGEST_URL|v31_ingest_snapshot|OFFICIAL V31" ibkr_bridge.py
python3 tools/v31_market_open_runner.py --dry-run
python3 tools/v31_market_open_runner.py --ticker SPY --right P --target-dte 45 --otm-pct 0.10
READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)" python3 tools/v31_operational_check.py --ticker SPY
python3 tools/publish_v31_snapshot_from_runtime.py
python3 tools/publish_v31_snapshot_from_runtime.py --publish
READ_ACCESS_TOKEN="$(security find-generic-password -a "$USER" -s stock-ultimus-read-access-token -w)"
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" https://trading-engine-p097.onrender.com/gpt_v31_trade_decision/QQQ
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" https://trading-engine-p097.onrender.com/gpt_v31_daily_recommendations
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" https://trading-engine-p097.onrender.com/v31_daily_recommendations
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" https://trading-engine-p097.onrender.com/v31_outcome_tracking_status
curl -sS -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" https://trading-engine-p097.onrender.com/v32_strategy_performance
curl -sS -X POST -H "X-Stock-Ultimus-Read-Token: $READ_ACCESS_TOKEN" "https://trading-engine-p097.onrender.com/v31_evaluate_pending_outcomes?dry_run=true&limit=25&checkpoint=EOD"
```
