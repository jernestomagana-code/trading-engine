# Historial de decisiones y resultados v1

La consola consolida `runtime/v32_decision_journal.json` y
`runtime/v32_outcomes_journal.json` para mostrar trazabilidad decisión→resultado,
cobertura de decisiones accionables, métricas por estrategia y progreso hacia una
muestra profesional.

La revisión de parámetros permanece bloqueada hasta acumular al menos 30 resultados
cerrados y completos. El panel es informativo: no autoriza ejecución ni cambios
automáticos de parámetros.

El payload consolidado está disponible localmente en `GET /decision-outcomes`.
