# Stock Ultimus Strategy Regime Policy v1

Esta politica define como cambia la evaluacion de estrategias segun el regimen de mercado. No autoriza operaciones; solo agrega contexto, cautelas y bloqueos de investigacion.

## Regimenes cubiertos

- `BULLISH_LOW_VOL`: tendencia alcista con volatilidad contenida. Favorece puts garantizados y filtros CANSLIM; cuidado con calls cubiertas que limiten upside.
- `NEUTRAL_RANGE`: mercado lateral. Permite puts garantizados y calls cubiertas; Iron Condor sigue en cautela/research-only.
- `BEARISH_OR_CORRECTION`: correccion o deterioro tecnico. Favorece manejo defensivo con covered calls; reduce agresividad de puts.
- `HIGH_VOL_EVENT_RISK`: volatilidad elevada, eventos macro/earnings o spreads deteriorados. Eleva estandar de liquidez y bloquea estrategias research-only sensibles a eventos.
- `INTRADAY_TREND`: tendencia intradia con contexto premarket claro. Solo aplica a futuros intradia; no debe activar estrategias de opciones swing.

## Uso operativo

El regimen debe influir en cautela, sizing, delta preferida, DTE y blockers, pero nunca debe saltarse:

- `WAIT_OPTIONS_DATA`
- contexto de cuenta/posicion
- reglas de riesgo
- revision manual
- ausencia de orden automatica

## Promocion de research-only

Una estrategia como `IRON_CONDOR` no puede pasar a activa solo por intuicion. Requiere:

- al menos 30 outcomes cerrados,
- cobertura de al menos 3 regimenes,
- expectancy R positiva,
- max adverse excursion dentro de limite,
- exit playbook definido,
- metricas de outcome definidas,
- version bump,
- revision manual y seguridad.

Bloqueadores duros de promocion:

- `AUTO_ORDER_EXECUTION_REQUIRED`
- `UNDEFINED_MAX_LOSS`
- `MISSING_EXIT_PLAYBOOK`
- `MISSING_OUTCOME_METRICS`
- `UNTESTED_EVENT_RISK`
