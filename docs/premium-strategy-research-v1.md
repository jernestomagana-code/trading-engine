# Investigación de nuevas estrategias de prima — etapa 1

Estado: `RESEARCH/PAPER ONLY`. Ninguna salida de este módulo es una orden ni puede alcanzar `ENTRY_READY`.

## 1. Volatilidad alrededor de earnings en candidatos CANSLIM

El universo parte de candidatos CANSLIM aprobados y con cobertura de datos mínima de 85%. La fecha y el horario del earnings deben estar confirmados. La hipótesis compara entradas uno, dos y tres días antes del evento, con vencimientos de 7, 14 y 21 días posteriores.

Sólo se investigan dos estructuras iniciales:

- Put asegurada con efectivo, con delta 10–15, cuando aceptar las acciones sea coherente con cartera y riesgo.
- Cóndor asimétrico de riesgo definido cuando se quiera capturar caída de volatilidad sin pérdida ilimitada.

No se permite como opción predeterminada el short strangle descubierto ni la proporción de dos puts por un call: esa proporción no iguala el riesgo extremo de la pata call.

La oportunidad queda bloqueada si no alcanza IV percentile 70, IV rank 50, prima implícita del evento 1.15 veces su referencia histórica, IV/volatilidad realizada 1.15, liquidez suficiente o si la pérdida de estrés supera 2% de la cuenta. La salida investigada será la primera sesión líquida después del evento, 35–50% del crédito, o como máximo dos sesiones después.

## 2. Put de largo plazo en SPY y RSP

El backtest debe comparar, sin elegir de antemano al ganador:

- 120, 150 y 180 DTE.
- Delta 10, 12, 14, 15 y 20.
- Objetivos de 50% y 60% del crédito.

La entrada requiere IV percentile mínimo 50, IV/volatilidad realizada de al menos 1.15 y una diferencia mínima de tres puntos de volatilidad. SPY y RSP se evalúan por separado porque su liquidez no es equivalente. Cada ciclo queda limitado a 30% de capacidad y la exposición agregada SPY+RSP a 40%. Debe existir efectivo reservado o margen de estrés verificable.

## 3. Qué deben demostrar las pruebas

Una combinación no pasa a `PAPER_ELIGIBLE` sólo por ganar. Debe incluir al menos 40 operaciones cerradas, 15 fuera de muestra, tres años distintos, regímenes alcista, bajista y alta volatilidad, los episodios 2008, 2011, 2015–2016, 2018, 2020 y 2022, profit factor mínimo 1.20 y drawdown máximo 25%.

Los resultados aportados inicialmente son evidencia útil para formular la hipótesis, pero no satisfacen esta puerta: abarcan aproximadamente abril de 2024 a abril de 2026 y sólo 7–9 observaciones. Por ello no se consideran todavía validación estadística.

## 4. Estados posibles

- `RESEARCH_BLOCKED`: faltan datos o falla una regla.
- `RESEARCH_CANDIDATE`: merece backtest o seguimiento, pero no paper ni operación.
- `PAPER_ELIGIBLE`: superó la puerta estadística y de estrés; aún requiere autorización separada para cualquier fase posterior.

El evaluador fija siempre `execution_authorized: false`, `not_order_instruction: true` y `maximum_state: PAPER_ELIGIBLE`.

## 5. Cobertura de datos — etapa 2

El archivo `runtime/premium_strategy_data_readiness_latest.json` indica, sin ocultar faltantes, si existe evidencia suficiente. La captura prospectiva conserva únicamente cotizaciones IBKR que ya contienen bid, ask, delta, IV, vencimiento, strike y subyacente; descarta filas incompletas y no consulta ni opera la cuenta.

Se mantienen almacenes separados para calendario de earnings confirmado, precios del subyacente, cotizaciones prospectivas e importación histórica de opciones vencidas. Esta separación evita mezclar precios actuales con backfills y permite auditar el origen de cada observación.

IBKR aporta cadenas y cotizaciones vivas, pero el backtest de periodos vencidos exige una fuente histórica licenciada o una exportación verificable. Hasta incorporar esa historia, el reporte debe permanecer en `DATA_COLLECTION_REQUIRED` aunque las cotizaciones del día estén completas.
