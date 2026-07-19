# Inteligencia avanzada de cartera v1

## Alcance

La Etapa 6B amplía el motor de estrés con cuatro capas de diagnóstico sobre todas
las cuentas de Control Tower:

- exposición por clase de activo, estilo, sector y factor macro;
- comportamiento histórico agregado de la cartera;
- correlaciones entre los subyacentes;
- Greeks consolidados de las posiciones de opciones.

El módulo es de solo lectura. No crea ni modifica órdenes y nunca autoriza una
liquidación automática.

## Datos y degradación controlada

Durante el refresco multicuenta se solicitan hasta seis meses de cierres diarios
por subyacente. La consulta se reutiliza entre cuentas para evitar duplicados.
Las opciones solicitan IV, delta, gamma, theta y vega cuando IBKR los ofrece.

Cada consulta queda limitada por tiempo. Si IBKR no entrega historia o Greeks,
el refresco continúa, el análisis queda `PARTIAL` y la consola muestra la
cobertura faltante. No se inventan valores.

## Métricas

- Cobertura histórica ponderada por exposición.
- Volatilidad anualizada de la cartera.
- Peor retorno diario, expected shortfall histórico al 95% y drawdown máximo.
- Pares con correlación superior al umbral configurado.
- Dollar delta, theta diario, vega por punto y aproximación gamma ante 1%.
- Factor dominante dentro de cada grupo.

La exposición de opciones utiliza delta equivalente cuando existen delta y
precio histórico del subyacente; de lo contrario usa prima como proxy y lo
declara en `exposure_basis`.

## Configuración y salidas

La clasificación y los umbrales están en
`config/portfolio_factor_policy.json`. El resultado persistido se escribe en
`runtime/portfolio_factor_latest.json` y la API local se expone en
`/portfolio-factors`.

Todas las métricas son sensibilidades diagnósticas basadas en historia y no
constituyen pronósticos, VaR regulatorio ni instrucciones de inversión.
