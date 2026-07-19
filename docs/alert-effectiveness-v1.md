# Efectividad del alertamiento v1

La consola calcula métricas conservadoras sobre los diarios sincronizados de
decisiones y resultados:

- cobertura de seguimiento de alertas de entrada;
- alertas acertadas y falsas alarmas verificadas;
- oportunidades perdidas y bloqueos de riesgo correctos;
- precisión verificada, tiempo de resolución y atribución de fuente;
- consolidación de decisiones lógicamente duplicadas.

Una clasificación sólo se contabiliza cuando existe un resultado cerrado
vinculado. Con una muestra sin cierres, la consola muestra `Sin muestra` y
`ESPERANDO RESULTADOS`, nunca un cero que pueda interpretarse como efectividad
perfecta. Se requieren 30 alertas resueltas antes de considerar la muestra
revisable. Ninguna métrica autoriza órdenes ni cambios automáticos de reglas.

El payload está disponible localmente en `GET /alert-effectiveness`.
