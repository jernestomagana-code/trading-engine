# Implementación de la auditoría UX · 9 de septiembre de 2026

La auditoría original está en `auditoria-ux-astra-2026-09-07.md`. Este documento registra la implementación y sus límites; los hallazgos originales se conservan como evidencia histórica.

## Cambios implementados

| Hallazgos | Resultado |
| --- | --- |
| 1, 8, 16 | Los formularios conservan la acción pulsada. Revisar, posponer y marcar revisado tienen confirmación y recuperación de errores sin perder notas. Las revisiones caducan al cambiar de día en CDMX; se puede deshacer. La postergación es de 5, 15 o 60 minutos según prioridad. |
| 2, 10 | Los enlaces abren la vista y el detalle correspondiente, incluyendo CANSLIM y posiciones identificadas por cuenta. Los filtros de estrategia incluyen las secciones asociadas. |
| 3 | El estado de acciones usa horario de Nueva York, festivos y cierres anticipados. Se distingue del horario del programador. El calendario no afirma que los futuros compartan sesión con las acciones. |
| 4, 7 | RSP consulta capacidad disponible de la cuenta de retiro con vigencia comprobada; no sustituye esos fondos por los de otra cuenta. La salud de la cuenta y la evaluación de cada estrategia se explican por separado. |
| 5, 9, 11, 12 | Hoy ofrece una siguiente revisión con enlace directo. Se distinguen prioridad y plan; los textos principales usan español. Los detalles de riesgo, diagnóstico y cierre se pueden desplegar. |
| 6 | Un resultado histórico no cierra visualmente una posición actual por coincidir el símbolo. Las vinculaciones requieren cuenta e identificador de operación; los registros sin vínculo quedan separados. |
| 13, 14 | Las cifras de futuros identifican su fuente y etapa. Las ideas de investigación muestran lo que falta para avanzar y no presentan campos de ejecución artificiales. |
| 15, 16 | Navegación horizontal móvil, controles accesibles y foco visible; el modo foco sigue disponible en móvil. |
| 17, 18 | Actividad permite revisar acciones registradas y filtrar expedientes. Las sesiones se separan por inactividad y las visitas QA no generan métricas de uso. Los contadores no equivalen a validación humana. |
| 19, 20 | Calendario, presentación compartida y cliente JavaScript se separaron del archivo principal. Se añadieron regresiones y un escenario aislado con datos ficticios para probar interacciones. |

## Validación realizada

- Suite completa: **682 pruebas, 0 fallos, 0 errores, 0 omitidas**.
- Sintaxis del cliente JavaScript y comprobación del diff correctas.
- Escenario aislado: navegación al detalle y cuenta correctos, CANSLIM, filtros, acciones de revisión, deshacer y conservación de notas ante un error recuperable.
- Anchuras de 390 y 320 píxeles: navegación y vistas comprobadas sin desbordamiento horizontal de página. Cinco vistas recorridas durante la revisión.
- Consola instalada a 1280 píxeles: Hoy, Cartera y Oportunidades verificadas; cero enlaces internos sin destino, cero identificadores duplicados y ningún error de navegador registrado durante esta comprobación.

## Instalación local

Servicio `com.stockultimus.local-console` actualizado y reiniciado correctamente. Los cinco archivos de implementación principales coinciden byte a byte con los del proyecto. Consola disponible en http://127.0.0.1:8765/console.

Respaldo previo: `/private/tmp/ultimus-console-backup-20260909-130633`. Es temporal y puede ser eliminado por el sistema. El runtime compartido se conservó. Las pruebas de acciones se realizaron sobre el diario temporal de la fixture, no sobre las revisiones reales.

## Pendiente de validación de producto

Se requiere observar sesiones reales para medir comprensión, tiempo hasta la siguiente revisión y recuperación ante errores. No se han realizado esas sesiones ni validado operaciones financieras reales.

Los cierres anticipados explícitos del calendario cubren 2026–2028 y requieren mantenimiento posterior; no se implementó un calendario contractual completo de futuros. Los registros históricos sin identificadores suficientes siguen sin poder asociarse con certeza a una operación. La extracción de módulos reduce el acoplamiento, pero el archivo principal todavía concentra responsabilidades y admite una refactorización posterior.


## Seguimiento adicional · ayuda y validación

Se actualizó la guía oficial servida por **Ayuda**: acciones de revisión, plazos de postergación, caducidad diaria, recuperación, identificación de expedientes, capacidad de retiro y filtros. Se añadió un recorrido de seis tareas con registro de dificultades y criterios para priorizar correcciones. Es un protocolo preparado, no evidencia de sesiones realizadas.

Validación de esta actualización documental: 39 pruebas de consola y ayuda correctas. La guía se instala sin reiniciar el servicio. Los pendientes de calendario contractual de futuros, conciliación de registros sin identificadores y observación real permanecen explícitos; no se completan infiriendo datos.


## Seguimiento · calendario contractual de futuros

Se integró `tradingHours` y `timeZoneId` de IBKR en la consulta existente del contrato explícito MNQ/MES. La señal principal muestra el estado según calendario; admite sesiones nocturnas y cierres explícitos, y rechaza horarios ambiguos, vencidos o fuera de cobertura. No hay un calendario fijo de CME ni inferencia de rollover. Fuente del formato: https://interactivebrokers.github.io/tws-api/classIBApi_1_1ContractDetails.html.

Seis regresiones cubren límites de sesión, festivos, cobertura, datos inválidos, verano/invierno y separación entre contratos. La recepción real del horario depende de una señal vigente con contrato explícito y de TWS; su ausencia no se interpreta como mercado cerrado.

Validación: suite completa de 687 pruebas correcta; tras añadir una regresión adicional de aislamiento de contrato, las 40 pruebas de futuros pasan.


## Seguimiento · coherencia de RSP

Se corrigió el estado del Centro de oportunidades cuando el motor pide capacidad, capital o margen sin añadir bloqueos explícitos: ahora muestra Bloqueada. La gestión reconoce WITH_SHARES y los textos de gestión conocidos se traducen desde los estados del motor. El detalle distingue existencia de cadena y fondos guardados de vigencia confirmada, y muestra la edad del reporte sin atribuirla a una actualización del broker. Se añadieron dos regresiones para estos casos.


## Seguimiento · 10 de septiembre · conciliación de revisiones

Se eliminó la asociación por ticker como respaldo en la evaluación del diario de gestión. Ahora se exige coincidencia única de identificador de posición y se respeta la cuenta registrada. Las nuevas revisiones guardan el alias de cuenta. Los expedientes explican la evidencia que falta y permiten filtrar todos los vínculos incompletos; el identificador de posición ya no se presenta como ciclo de operación. No se modificaron registros históricos ni se inventaron asociaciones.

Se añadieron regresiones para impedir cruces por ticker, por cuenta y por identificadores ambiguos, y para comprobar la explicación del ciclo faltante. La conciliación de registros históricos sin evidencia suficiente y la observación de sesiones humanas siguen pendientes de datos reales.


## Seguimiento · 13 de septiembre · confirmación por cuenta

La huella de revisión incorpora alias y alcance de cuenta. La selección del evento respeta su cuenta y los identificadores duplicados no permiten ocultar posiciones como revisadas. Se conserva el diario histórico; las huellas anteriores pueden volver a requerir confirmación. Se añadió una regresión que cubre cuenta correcta, cuenta distinta e identificador duplicado.

### Pendientes que requieren evidencia externa

- Observar recorridos reales de usuario con el protocolo de Ayuda; no se ha medido comprensión ni mejora de tiempos.
- Verificar recepción de horarios de IBKR con una señal vigente y contrato explícito. La integración ya está implementada.
- Conciliar los históricos a los que les faltan identificadores, únicamente cuando exista evidencia suficiente. El filtro de vínculos incompletos ya los identifica.

La refactorización adicional del archivo principal es mantenimiento posterior, no una validación de experiencia ni una corrección funcional que pueda declararse necesaria sólo por su tamaño.

## Seguimiento · 13 de septiembre · actividad sin mercado

Actividad reciente incorpora las acciones locales sobre alertas además de tareas y revisiones de posiciones. Un filtro permite separar los tres tipos y se combina con el período desde la última visita. Los textos distinguen una alerta vista, en seguimiento, descartada, cerrada o una ejecución informada pendiente de conciliación; ninguno confirma por sí solo una operación en el broker.

Este cambio puede validarse con mercado cerrado y datos ficticios. Se añadió cobertura automática de la presencia, clasificación y texto de las acciones de alerta.

La misma comprobación visual detectó códigos internos todavía visibles en el resumen de investigación. Los estados y el límite máximo se muestran ahora como **Recopilación de datos en curso**, **Sólo investigación** y **evaluación simulada**, conservando los códigos originales únicamente en las fuentes técnicas.

El explorador de expedientes abre ahora en **Posiciones actuales**. En la verificación local había 89 casos totales y cuatro posiciones actuales; el resto sigue disponible mediante los filtros. Esto reduce la carga inicial de Actividad sin borrar ni modificar registros.

## Seguimiento · actividad unificada, recorridos y accesibilidad

La construcción del historial cotidiano se extrajo a `console_activity.py`. Actividad puede mostrar tareas, revisiones de posiciones, acciones sobre alertas, el último resultado de actualización de fuentes y señales de futuros vencidas. Las señales vigentes quedan fuera de esta lista y continúan en Oportunidades. Los eventos se deduplican por identificador y pueden filtrarse por tipo y período.

El recorrido reutilizable `scripts/check_console_responsive.cjs` cubre ahora 320, 390 y 1280 píxeles; cinco vistas, modo foco y su estado accesible, filtro de Actividad, alcance inicial de posiciones, enlace profundo CANSLIM, Atrás/Adelante, desbordamiento, identificadores duplicados, nombres de formularios y errores del navegador. Usa por defecto la fixture aislada y no ejecuta acciones operativas.

La revisión directa de la consola instalada a 320 píxeles confirmó ancho de página sin desbordamiento, navegación horizontal disponible, modo foco presente, cero controles sin nombre y cero identificadores duplicados. Ocho pasos consecutivos de teclado mantuvieron foco visible; los campos medían 43–45 píxeles. Los botones de Actividad que medían 36 píxeles recibieron un mínimo móvil de 44 píxeles. La prueba no sustituye una evaluación formal con lector de pantalla.

Validación final de este corte: **698 pruebas, 0 fallos, 0 errores y 0 omitidas**. La consola local instalada mostró una actualización parcial de datos y una señal MNQ vencida en Actividad, conservó cuatro posiciones actuales como alcance inicial, no desbordó a 320 píxeles y no produjo errores del navegador.

## Seguimiento · reducción de ancho de banda

Tras alcanzar el límite de 5 GB del workspace Hobby de Render, se habilitó compresión gzip para respuestas mayores de 1 KB y la consola comenzó a solicitar ventanas acotadas: 100 señales, 100 revisiones, 100 registros de aprendizaje y 200 de rendimiento. Sobre el conjunto real conservado localmente, gzip redujo 3,177,069 bytes a 186,050 bytes, una reducción aproximada de 94.1 % antes de considerar los límites menores. La consola instalada solicita gzip y lo decodifica de forma explícita.

Validación de este seguimiento: **700 pruebas, 0 fallos, 0 errores y 0 omitidas**. `cloudflared` ya está instalado en la Mac, pero todavía no existe una identidad de túnel, configuración ni credenciales locales; un túnel estable requiere vincular una cuenta de Cloudflare y un dominio antes de sustituir la URL pública de Render.

El 14 de septiembre Render fue reactivado y el cambio `ab8353f` se desplegó en producción. La raíz pública y la ruta diaria de futuros respondieron HTTP 200 con `Content-Encoding: gzip`; la verificación de autenticación confirmó producción `READY`, acceso autorizado 200 y acceso sin token 401. Tras un 502 transitorio durante el arranque, una segunda actualización completa de las once fuentes terminó `READY` sin errores.
