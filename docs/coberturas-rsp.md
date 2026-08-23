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

Las alternativas atraviesan compuertas obligatorias en este orden: calidad de
ejecución (bid/ask y spread máximo de 25%), alineación del strike con
soporte/resistencia, expected move y walls gamma del vencimiento, prima
ejecutable mínima de USD 100 y ganancia máxima mínima de USD 100. Para ventas,
la prima operativa se calcula con el bid conservador; el punto medio se conserva
sólo como referencia. En un buy-write, la consola separa el ingreso aportado por
la call de la apreciación de las acciones hasta el strike. Los contratos que
fallen una compuerta permanecen en diagnóstico, pero no se recomiendan.

Comprar 100 acciones sin call se presenta únicamente como comparador: conserva
todo el upside, pero requiere una tesis direccional alcista confirmada. Si no
hay una estructura válida o el contexto cargado dice esperar, **esperar** es la
recomendación explícita; el motor no elige automáticamente la alternativa menos
mala.

La consola separa además **candidatos cercanos** de las entradas aprobadas. Un
candidato cercano cumple casi todas las compuertas y falla exactamente una
condición no crítica; se muestra para monitoreo, pero nunca se rotula como
entrada. Un `possible_mode: esperar` genérico penaliza su ranking sin vetarlo
por sí solo. Advertencias explícitas como riesgo de evento, resultados, no
operar o volatilidad extrema continúan siendo bloqueos duros.

El refresh RSP usa un único límite operativo de spread de 25%, sin heredar el
límite general más estricto de otras estrategias. Cada combinación nueva de
cadena y contexto guarda una observación deduplicada con candidatos evaluados,
aprobados, cercanos y causas de rechazo. Este historial permite revisar después
de varias sesiones si las compuertas producen oportunidades reales sin relajar
la prima mínima ni la disciplina técnica.

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
