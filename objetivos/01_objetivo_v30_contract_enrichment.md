# Objetivo V30 - Bridge Contract Execution Enrichment

El sistema ya conecta IBKR local con Render mediante `ibkr_bridge.py` y `app/main.py`.

## Estado actual

- `ibkr_bridge.py` lee precios, portafolio y opciones desde IBKR.
- `app/main.py` en Render recibe snapshots y expone dashboards/endpoints GPT.
- V29.1 ya clasifica correctamente `WAIT_OPTIONS_DATA` cuando faltan datos ejecutables.
- El bloqueo principal es que muchos contratos aparecen como `PRICE_WITH_GREEKS_NO_BIDASK` y quedan en `RADAR` o `WAIT_OPTIONS_DATA`.

## Objetivo

Modificar principalmente `ibkr_bridge.py` para publicar contratos ejecutables completos al snapshot maestro.

## Campos minimos por contrato

- `ticker`
- `strategy`
- `decision`
- `score`
- `strike`
- `expiration`
- `dte`
- `bid`
- `ask`
- `mid`
- `spread`
- `spread_pct`
- `delta`
- `gamma`
- `theta`
- `vega`
- `iv`
- `volume`
- `open_interest`
- `can_operate`
- `data_quality`
- `missing_confirmations`
- `recommendation`
- `reason`

## Regla

No marcar `ENTRY_READY` si faltan `bid`, `ask`, `spread`, `spread_pct`, `strike`, `expiration`, `dte` o `delta`.

## Resultado esperado

`GET /gpt_v29_trade_decision/QQQ` debe pasar de `WAIT_OPTIONS_DATA` a `ENTRY_READY` unicamente cuando exista un contrato ejecutable real.
