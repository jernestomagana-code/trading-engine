# Mantenimiento preventivo v1

La consola revisa diariamente:

- antigüedad y validez JSON de fuentes operativas críticas;
- estado reciente de la conexión IBKR;
- presencia de procesos locales programados;
- número y tamaño de archivos en `runtime/`;
- archivos individuales mayores de 25 MB;
- espacio libre en disco;
- vigencia de auditorías, seguimiento y reportes ejecutivos.

Los umbrales de antigüedad son más amplios durante fines de semana para evitar
alertas falsas por mercado cerrado. El reporte se guarda en
`runtime/preventive_maintenance_latest.json` y su historial diario es
idempotente.

El proceso se ejecuta todos los días a las 06:45 y puede lanzarse manualmente
desde la consola. Es deliberadamente no destructivo: nunca elimina archivos,
rota históricos, reinicia procesos ni toca órdenes automáticamente.
