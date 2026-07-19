# Motor de riesgo y alertamiento de cartera v1

## Propósito

Convertir los snapshots sanitizados de Control Tower en un diagnóstico explicable por cuenta y consolidado. Es una capa de decisión y mantenimiento: no coloca órdenes, no liquida posiciones y no modifica el broker.

## Fuentes y métricas

El motor usa las métricas de Account Summary entregadas por IBKR:

- `NetLiquidation`: base patrimonial de la cuenta.
- `AvailableFunds`: fondos disponibles para operar.
- `ExcessLiquidity`: colchón antes de una posible liquidación.
- `MaintMarginReq`: margen requerido para mantener la cartera.
- `GrossPositionValue`: exposición bruta de acciones y opciones de renta variable.
- `TotalCashValue`: efectivo reconocido por la cuenta.

Las razones derivadas son:

- colchón de liquidez = `ExcessLiquidity / NetLiquidation`;
- fondos disponibles = `AvailableFunds / NetLiquidation`;
- uso de margen = `MaintMarginReq / NetLiquidation`;
- apalancamiento = `GrossPositionValue / NetLiquidation`;
- concentración entre cuentas = NAV de la cuenta / NAV consolidado.

Las opciones con cantidad negativa generan una alerta de exposición corta. El motor no las denomina “descubiertas” porque la cobertura no puede inferirse sólo con Position y Account Summary.

## Política configurable

La política versionada está en `config/portfolio_risk_policy.json`. Sus valores son umbrales operativos conservadores, no recomendaciones de inversión. Se pueden modificar globalmente o por alias mediante `account_overrides`.

Reglas incluidas:

- antigüedad y disponibilidad de datos;
- NAV ausente o no positivo;
- métricas esenciales ausentes;
- colchón de liquidez reducido;
- fondos disponibles reducidos;
- margen de mantenimiento elevado;
- apalancamiento elevado;
- concentración del NAV entre cuentas;
- efectivo negativo;
- opciones cortas presentes.

## Severidades y decisión

- `CRITICAL` → `BLOCKED` / `NO_NEW_RISK`.
- `HIGH` → `ACTION_REQUIRED` / `REVIEW_REQUIRED`.
- `WATCH` → `WATCH` / `MONITOR`.
- sin alertas → `READY` / `CLEAR`.

Una severidad de dominio no causa por sí sola un error técnico del proceso. Para automatizaciones que sí necesiten códigos de salida estrictos se puede usar `--strict-exit`.

## Persistencia y ciclo de vida

- Estado actual: `runtime/portfolio_risk_latest.json`.
- Historial: `runtime/portfolio_risk_history.json`.
- Transiciones: `OPENED`, `SEVERITY_CHANGED` y `RESOLVED`.
- Los IDs de alerta son deterministas; reevaluar la misma condición no crea duplicados.
- Todos los archivos se escriben de forma atómica y excluyen IDs reales de broker.

## Operación

El botón **Refrescar todas las cuentas** actualiza broker, Control Tower y riesgo en una sola ejecución. El botón **Reevaluar riesgo** vuelve a aplicar la política sin consultar ni modificar el broker.

Ejecución manual:

```bash
python3 scripts/evaluate_portfolio_risk.py
```

Ruta JSON local sanitizada: `/portfolio-risk`.

## Criterios de aceptación

- Toda cuenta vencida, incompleta o sin métricas esenciales falla cerrada.
- Cada alerta muestra regla, severidad, cuenta, valor, umbral y siguiente paso.
- La misma condición conserva el mismo ID y no duplica eventos.
- Una condición desaparecida genera una transición `RESOLVED`.
- Ningún artefacto contiene una clave `account_id` o un ID real.
- `execution_authorized=false`, `automatic_liquidation_authorized=false` y `not_order_instruction=true` permanecen explícitos.
