# Coberturas RSP

Modulo independiente dentro de Stock Ultimus para recomendar la estrategia RSP de cobro de prima.

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
