# Validación oficial IBKR what-if v1

## Objetivo

La Etapa 6D1 conecta las alternativas virtuales de rebalanceo con el preview
oficial de margen y comisiones de IBKR. Cada solicitud usa `whatIf=true` y
`transmit=false`; no crea una orden activa.

Todo se opera y visualiza desde la consola local. Los IDs reales de cuenta se
leen desde Keychain únicamente dentro del proceso y nunca se guardan ni muestran.

## Barreras de seguridad

- Solo se aceptan reducciones o cierres de posiciones existentes.
- La cantidad posterior no puede aumentar exposición ni cambiar de signo.
- El contrato debe coincidir exactamente con una posición viva de la misma cuenta.
- La acción debe ser `SELL` para reducir un largo o `BUY` para reducir un corto.
- Cada objeto exige `whatIf=true` y `transmit=false` antes de llamar a IBKR.
- Se comparan las órdenes abiertas antes y después mediante una huella estable.
- Cualquier cambio en esa huella produce `SAFETY_VIOLATION`.
- El número de previews está limitado por política.

## Resultados

Por acción se muestran cambios de margen inicial, margen de mantenimiento,
equity-with-loan, comisión y advertencias de IBKR. Las sumas de margen se etiquetan
como previews independientes: no representan una simulación conjunta de cesta,
porque IBKR evalúa cada solicitud contra la cartera vigente.

La salida se persiste en
`runtime/portfolio_rebalance_whatif_latest.json` y está disponible en la API local
`/portfolio-rebalance-whatif`.

## Limitaciones

Un preview puede ser parcial si TWS, permisos o el contrato no entregan margen o
comisión. Esta capa no estima impuestos, deslizamiento ni impacto de mercado; esos
costos corresponden a la siguiente subetapa 6D2.
