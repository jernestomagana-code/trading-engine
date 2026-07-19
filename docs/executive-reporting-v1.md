# Reporte ejecutivo automático v1

Stock Ultimus genera dos reportes sanitizados dentro de la consola:

- **Diario:** estado de cuentas, score de riesgo, alertas prioritarias,
  evidencia, mantenimiento y acciones pendientes.
- **Semanal:** agrega eventos de riesgo abiertos/resueltos durante siete días y
  conserva el avance de decisiones y resultados.

Los reportes se guardan como JSON y Markdown en `runtime/` y se archivan de
forma idempotente en `runtime/executive_report_history.json`. La consola permite
regenerarlos manualmente y expone `GET /executive-report`.

Los horarios locales son lunes a viernes a las 17:45 para el reporte diario y
viernes a las 18:00 para el semanal. Ninguno envía comunicaciones, contiene
identificadores sensibles, autoriza órdenes o modifica reglas automáticamente.
