# Pendientes UX · evidencia revisada el 13 de septiembre de 2026

La implementación y sus pruebas se documentan en `implementacion-ux-2026-09-09.md`. Este corte distingue trabajo instalado de evidencia todavía faltante.

| Pendiente | Evidencia local disponible | Qué permite cerrarlo |
| --- | --- | --- |
| Conciliación de decisiones con operaciones | 49 decisiones; las 49 carecen de cuenta y ciclo en campos principales. Una conserva referencia de señal. | Evidencia de cuenta y operación que corresponda inequívocamente al registro. Una señal no confirma una ejecución. |
| Conciliación de resultados | 26 resultados; los 26 carecen de cuenta y ciclo en campos principales y conservan referencia de señal. | Determinar primero si cada resultado es seguimiento de una señal, simulación o ejecución; sólo asociarlo a una posición real con evidencia suficiente. |
| Validación de uso | 4 sesiones registradas, 2 acciones confirmadas, 0 errores de acción registrados. | Observar el recorrido de seis tareas de Ayuda y anotar comprensión, ayuda requerida y dificultades. Cero errores registrados no demuestra ausencia de errores. |
| Horario contractual de futuros | Integración y regresiones implementadas. Este diagnóstico no consulta TWS ni prueba el horario en vivo. | Recibir y comprobar un calendario de IBKR para una señal vigente con contrato explícito. |

Actividad reciente ya incluye tareas, posiciones y acciones sobre alertas, con filtro por tipo y período. Esta parte del hallazgo 17 puede validarse con mercado cerrado; la comprensión del recorrido completo sigue requiriendo observación humana.

Actualización posterior: Actividad también incorpora cambios de actualización de fuentes y señales vencidas, construidos desde un módulo de presentación separado. Se amplió el recorrido automatizado y se verificaron teclado, nombres accesibles y 320 píxeles. Permanece pendiente una sesión formal con lector de pantalla y la observación humana del recorrido completo.

Los números reflejan los diarios locales al momento de la revisión. La ausencia de campos principales no demuestra ausencia de toda evidencia: podrían existir documentos o referencias adicionales que requieran conciliación. No se corrigieron históricos ni se atribuyeron operaciones por coincidencia de símbolo.

## Comprobación con mercado abierto · 14 de septiembre de 2026

A las 13:10 CDMX, IBKR aparecía conectado y la consola tenía datos de cuenta vigentes. La actualización de fuentes terminó en estado parcial porque las once rutas remotas devolvieron HTTP 503. Una comprobación directa de salud confirmó que el servicio de Render estaba suspendido por su propietario. La consola mostró cero señales de futuros recibidas hoy; por ello no existe todavía una señal vigente con contrato explícito que permita validar cotización y horario contractual desde IBKR.

Los diarios continúan con 49 decisiones y 26 resultados sin cuenta/ciclo en sus campos principales. No apareció evidencia nueva que permita conciliarlos. La telemetría local aumentó a cinco sesiones y tres acciones confirmadas, sin errores de acción, pero sigue sin sustituir la observación humana.

El diagnóstico puede repetirse con `python3 scripts/check_console_ux_evidence.py`. Sólo lee archivos y muestra agregados; distingue archivos faltantes, ilegibles y esquemas inesperados. No envía mensajes, no consulta el broker y no cambia registros.

Las correcciones funcionales identificadas en las últimas revisiones están instaladas y la última suite completa pasó 698 pruebas. Actividad ya reúne tareas, posiciones, alertas, actualizaciones de datos y señales vencidas; la comprobación instalada confirmó ambos tipos nuevos y controles táctiles de 44 píxeles a 320 píxeles de ancho.
