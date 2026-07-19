# Control Tower multi-cuenta v1

## Objetivo

Dar una vista consolidada y separada por cuenta de la capacidad y las posiciones visibles en IBKR. La función es exclusivamente de lectura: no recibe ni ejecuta instrucciones de orden.

## Contrato operativo

- Cada cuenta se identifica en disco sólo por su alias local.
- Los IDs reales se consultan desde Keychain en memoria y no se guardan en snapshots, registros ni respuestas HTTP.
- Una sola conexión `readonly` obtiene el resumen y las posiciones; después los datos se separan por cuenta antes de persistirse.
- Cada snapshot vive en `runtime/accounts/<alias>/account_snapshot.json`.
- El consolidado vive en `runtime/broker_control_tower_latest.json`.
- Las escrituras JSON son atómicas para evitar archivos parciales durante una interrupción.
- `execution_authorized=false` y `not_order_instruction=true` forman parte de todos los artefactos públicos.

## Estados

- `READY`: todas las cuentas configuradas tienen capacidad válida y un snapshot de hasta 15 minutos.
- `PARTIAL`: hay al menos una cuenta lista o vencida, pero el conjunto no está completo.
- `WAIT_ACCOUNT_REFRESH`: ninguna cuenta tiene un snapshot utilizable.
- `STALE`: la cuenta tiene datos válidos, pero superó la antigüedad permitida.
- `CAPACITY_UNAVAILABLE`: IBKR respondió, pero no entregó ninguna métrica de capacidad; el sistema falla cerrado.

La consola recalcula la antigüedad al abrirse. Un snapshot que era `READY` no permanece verde indefinidamente.

## Operación

En la consola local, usar **Refrescar todas las cuentas**. El proceso consulta las cuentas configuradas, actualiza los archivos particionados y vuelve a generar el consolidado. La ruta JSON sanitizada es `/control-tower`.

Para una revisión técnica manual:

```bash
python3 scripts/refresh_multi_account_control_tower.py --host 127.0.0.1 --port 7496
```

## Criterios de aceptación

- El número de cuentas listas coincide con el número configurado.
- No hay advertencias, cuentas vencidas ni fallidas.
- La suma consolidada coincide con las cuentas individuales.
- No existe ninguna clave `account_id` ni un ID real en los artefactos persistidos.
- La acción de refresco termina sin errores de navegador y la consola no presenta desborde horizontal en escritorio o móvil.

## Límite de esta etapa

Esta versión entrega inventario, capacidad, posiciones y frescura multicuenta. Alertamiento por reglas de cartera, límites por cuenta, mantenimiento programado y acciones correctivas continúan en las siguientes etapas.
