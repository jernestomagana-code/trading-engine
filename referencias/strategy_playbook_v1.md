# Stock Ultimus Strategy Playbook v1

Este playbook define las estrategias productivas como reglas auditables. Ninguna estrategia autoriza ejecucion automatica; `ENTRY_READY` significa listo para revision manual.

## Estrategias activas

- `CASH_SECURED_PUT`: venta de put garantizada por efectivo para regimen alcista o neutral-alcista. Requiere tecnico, CANSLIM cuando aplique, contrato ejecutable y riesgo claro.
- `COVERED_CALL`: venta de call cubierta contra posicion existente. Requiere contexto de cuenta/posicion y contrato liquido.
- `INTRADAY_INDEX_FUTURES`: senales intradia sobre indices/futuros. Requiere contexto premarket, validacion tecnica y riesgo diario claro.

## Filtros

- `CANSLIM_GROWTH_FILTER`: filtro fundamental y de liderazgo. Puede bloquear ideas sobre acciones si falla, pero no es una orden ni estrategia ejecutable por si sola.

## Research-only

- `IRON_CONDOR`: queda en research-only hasta validar chains completas, fills teoricos, manejo de riesgo por alas y outcomes forward-tested.

## Prioridad de blockers

La prioridad no se debilita:

1. `NO_DATA`
2. `WAIT_ACCOUNT_CONTEXT`
3. `WAIT_MARKET`
4. `WAIT_OPTIONS_DATA`
5. `WAIT_TECHNICAL`
6. `RISK_BLOCKED`
7. `MANUAL_REVIEW`
8. `ENTRY_READY`

Si falta bid/ask/spread/spread_pct/delta/DTE/expiration/strike, la recomendacion debe permanecer en `WAIT_OPTIONS_DATA`, aunque el tecnico o CANSLIM esten confirmados.

## Morgan research loop

El agente Morgan puede proponer mejoras, pero solo pasan a produccion cuando se convierten en reglas versionadas, testeables y auditables. Ideas de traders top sin reglas medibles quedan en research-only.
