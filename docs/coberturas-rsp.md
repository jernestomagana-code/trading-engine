# Coberturas RSP

Modulo independiente dentro de Stock Ultimus para recomendar la estrategia RSP de cobro de prima.

La cotización actual de IBKR/runtime tiene prioridad sobre el spot pegado en
el JSON. El contexto gamma manual vence para decisiones nuevas después de
24 horas: al vencer, soportes, resistencias, expected move, call wall, put
wall y sesgo gamma se excluyen del cálculo hasta pegar una lectura nueva.
Esto no detiene la detección automática de posiciones ni la gestión de un
ciclo abierto.

La apertura diaria refresca automáticamente posición, capacidad y cadena
RSP de 7–14 DTE. Una recomendación sólo se presenta como revisable cuando la
cadena es fresca; bid, ask y spread siguen siendo obligatorios para considerar
un contrato ejecutable.

La cadena dedicada también se incluye en el snapshot durable sanitizado. Si
Render reinicia, el motor recupera su último timestamp y sus campos de
ejecución; no confunde el reinicio con una ausencia de datos.

## Alcance V0

- Activo unico: RSP.
- Cuenta real IBKR en modo lectura/recomendacion.
- Maximo 1 contrato inicial.
- No coloca ordenes ni autoriza ejecucion.
- Requiere revision humana antes de cualquier accion en IBKR.

## Flujo

1. Abrir `/coberturas`.
2. Cargar contexto manual de gamma: spot, expected move, call wall, put wall, soportes y resistencias.
3. Refrescar bridge IBKR con el perfil RSP semanal:
   - universo de opciones: RSP,
   - DTE objetivo: 7-14 dias,
   - ideal: 8 DTE,
   - maximo 1 lote inicial,
   - sin ejecucion automatica.
4. Revisar modo recomendado:
   - sin acciones: venta de put,
   - con acciones: covered call,
   - opcion abierta: manejar/rolar/cerrar antes de abrir otra.
5. Revisar candidatos y decidir manualmente en IBKR.

## Guardrails

Todos los payloads deben mantener:

- `execution_authorized: false`
- `not_order_instruction: true`
- `manual_review_required: true`
