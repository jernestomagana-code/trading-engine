# Historial de decisiones y resultados v1

La consola consolida `runtime/v32_decision_journal.json` y
`runtime/v32_outcomes_journal.json` para mostrar trazabilidad decisión→resultado,
cobertura de decisiones accionables, métricas por estrategia y progreso hacia una
muestra profesional.

La revisión de parámetros permanece bloqueada hasta acumular al menos 30 resultados
cerrados y completos. El panel es informativo: no autoriza ejecución ni cambios
automáticos de parámetros.

El payload consolidado está disponible localmente en `GET /decision-outcomes`.

## Seguimiento automático

El ciclo de post-cierre ya instalado ejecuta los checkpoints `EOD`, `PLUS_1D` y
`PLUS_5D`. Después de evaluar, descarga el diario remoto de resultados mediante
acceso de lectura, elimina campos sensibles y reemplaza atómicamente
`runtime/v32_outcomes_journal.json`. La consola muestra la última ejecución,
evaluaciones procesadas, pendientes y estado de sincronización. También permite
lanzar el mismo proceso manualmente con **Actualizar seguimiento ahora**.

El mismo ciclo sincroniza el diario de decisiones desde `GET /v32_decisions`.
Esto garantiza que `decision_id` y `signal_id` procedan del mismo repositorio
durable que los resultados y permite calcular cobertura real sin mezclar diarios
históricos incompatibles.
