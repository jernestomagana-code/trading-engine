# Validación oficial IBKR what-if v1

## Objetivo

La Etapa 6D1 conecta las alternativas virtuales de rebalanceo con el preview
oficial de margen y comisiones de IBKR. Cada solicitud usa `whatIf=true`. IBKR
exige además `transmit=true` para procesar la consulta; con `whatIf=true` ese flag
envía un preview al servidor y no crea una orden activa.

Todo se opera y visualiza desde la consola local. Los IDs reales de cuenta se
leen desde Keychain únicamente dentro del proceso y nunca se guardan ni muestran.

## Barreras de seguridad

- Solo se aceptan reducciones o cierres de posiciones existentes.
- La cantidad posterior no puede aumentar exposición ni cambiar de signo.
- El contrato debe coincidir exactamente con una posición viva de la misma cuenta.
- La acción debe ser `SELL` para reducir un largo o `BUY` para reducir un corto.
- Cada objeto exige `whatIf=true`; `transmit=true` se permite exclusivamente por
  el requisito del servidor para procesar el preview.
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

Si todos los previews vencen por tiempo de espera, la consola lo presenta como
`TWS_CONFIRMATION_REQUIRED`. Esto normalmente significa que TWS mantiene abierta
su confirmación de precauciones para órdenes API. La consola no acepta esa decisión
automáticamente: desactivar dichas precauciones es global y también afectaría
posibles órdenes reales futuras.

## Aislamiento del canal

El preview utiliza el cliente IBKR exclusivo `87`; los clientes operativos
`42`, `74`, `75` y `84` están prohibidos por política. Antes de conectar, el
runner se audita a sí mismo y se bloquea si detecta capacidad `placeOrder`.
La consola distingue dos niveles:

- `Canal sin ejecución real`: cliente exclusivo y superficie limitada a
  `whatIfOrder`.
- `Sesión TWS dedicada`: instancia separada confirmada mediante
  `STOCK_ULTIMUS_WHATIF_DEDICATED_TWS=1`.

La política no permite recomendar el bypass global de precauciones mientras la
sesión TWS dedicada siga en `NO`.

## Limitaciones

Un preview puede ser parcial si TWS, permisos o el contrato no entregan margen o
comisión. Esta capa no estima impuestos, deslizamiento ni impacto de mercado; esos
costos corresponden a la siguiente subetapa 6D2.
