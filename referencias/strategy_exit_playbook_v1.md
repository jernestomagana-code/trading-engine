# Stock Ultimus Strategy Exit Playbook v1

Este playbook define manejo y salida de posiciones como reglas auditables. Ninguna regla cierra, rollea, asigna ni abre operaciones automaticamente.

## Estados canonicos de salida

- `NO_POSITION`: no hay posicion viva que manejar.
- `MONITOR`: posicion abierta sin accion prioritaria.
- `TAKE_PROFIT_REVIEW`: revisar cierre manual por captura de prima.
- `ROLL_REVIEW`: revisar roll manual, solo si no aumenta riesgo sin justificacion.
- `ASSIGNMENT_REVIEW`: revisar asignacion posible o deseada.
- `EXIT_REVIEW`: revisar salida manual por tesis invalidada.
- `RISK_REVIEW`: revisar defensa por evento, tecnico, liquidez, reserva o cobertura.
- `EXPIRED_OR_CLOSED`: posicion expirada o cerrada.

## Cash Secured Put

Requiere posicion, contrato short put, precio del subyacente, mark/mid de opcion, credito de entrada, DTE, delta, reserva de efectivo, riesgo de evento y contexto tecnico.

- Toma de ganancia: revisar cierre manual si se capturo al menos 50% del credito y queda riesgo abierto.
- Roll: revisar solo cerca de vencimiento o delta elevada, y solo si reduce o no aumenta riesgo/cash reserve.
- Asignacion: revisar si el subyacente esta bajo strike y aceptar acciones cumple el plan.
- Riesgo: revisar defensa si hay evento activo, ruptura tecnica o falta reserva de efectivo.

Metricas: `premium_capture_pct`, `pnl_r`, `mfe_r`, `mae_r`, `assignment_rate`, `days_in_trade`, `roll_count`.

## Covered Call

Requiere acciones largas, contrato short call, precio del subyacente, mark/mid de opcion, credito de entrada, DTE, delta, costo base, preferencia de asignacion y contexto tecnico.

- Toma de ganancia: revisar cierre manual si se capturo al menos 50% del credito y se desea conservar la accion.
- Roll: revisar si la asignacion no es deseada y el nuevo contrato sigue cubierto por acciones.
- Asignacion: revisar si aceptar que las acciones sean llamadas es mejor que cerrar o rollear.
- Riesgo: bloquear cualquier manejo que deje call descubierta o aumente riesgo sin revision manual.

Metricas: `premium_capture_pct`, `pnl_r`, `mfe_r`, `mae_r`, `assignment_rate`, `called_away_return_pct`, `days_in_trade`, `roll_count`.

## Politica de mejora

Los parametros de salida no deben cambiar por intuicion aislada. Para revisar parametros se requiere muestra cerrada suficiente, idealmente al menos 30 outcomes por estrategia, cobertura de regimenes y cambio versionado de reglas.

`ENTRY_READY` sigue significando listo para revision manual de entrada. Este playbook aplica despues o durante una posicion, y tampoco autoriza ejecucion.
