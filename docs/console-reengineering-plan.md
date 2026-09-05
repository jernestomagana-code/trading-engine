# Reingeniería de consola — plan único

## Alcance aprobado

1. Hoy centrado en decisiones.
2. Vigencia y presentación de futuros.
3. Gestión de Cartera por posición.
4. Oportunidades separadas por estrategia, incluyendo earnings y puts largos.
5. Apertura y ciclos automáticos verificables.
6. Actividad, aprendizaje y revisión visual final.

## Avance del 4 de septiembre de 2026

Implementado: preparación plegada en Hoy, indicadores de posiciones por atender y entradas vigentes, navegación Actividad/Más, eliminación de futuros vencidos del centro de oportunidades, entradas de 3 minutos y contexto de 10 minutos, expiración de tarjetas en pantalla y registro separado en Actividad.

Validación: 653 pruebas automáticas. Estos cambios son la primera entrega de las etapas 1–2, no el cierre de toda la reingeniería.

También completado: una señal de futuros sin timestamp no se considera vigente; los contadores del centro de oportunidades y entradas de Hoy se actualizan al caducar tarjetas.

Segunda entrega: control de precio explícito del mismo instrumento, con cotización de hasta 30 segundos, stop y límite de entrada. Una señal sin esa comprobación sigue visible como «Verificar precio actual». Una cotización fuera del límite o del stop retira la señal de oportunidades, conservando su registro. El precio del disparo nunca sustituye a una cotización actual. Los objetivos TP1/TP2 usan también los campos nativos del motor. La pantalla retira la etiqueta de entrada lista cuando caduca la cotización.

Validación de esta entrega: 656 pruebas automáticas satisfactorias. No modifica los criterios de generación ni el envío de alertas.

Pendiente dentro de etapas 1–2: conectar una fuente independiente de cotizaciones actuales al control (no está verificado el suministro de esos campos en producción), comprobar su comportamiento con señales reales y completar evaluación visual de escritorio/móvil. El control verifica el precio observado, no demuestra que el stop no haya sido tocado antes. No se han implementado todavía las etapas 3–6. Siguiente trabajo: resolver la fuente de cotizaciones sin mezclar USTEC.F con MNQ ni índices con contratos distintos.

No cambiar criterios de entrada ni habilitar estrategias RESEARCH_ONLY como parte del rediseño visual. No confundir comprobaciones técnicas satisfactorias con validación de rentabilidad.

## Conexión y revisión visual — 4 de septiembre, siguiente entrega

- Implementada consulta automática en segundo plano a TWS, sólo lectura, para contratos MNQ/MES identificados por mes y año. Cache limitada y consulta de pantalla cada 5 segundos mientras existan tarjetas vigentes. Usa ask para LONG y bid para SHORT; rechaza datos congelados/demorados y contratos ambiguos.
- Prueba real satisfactoria de compra/venta de MNQU2026 y MESU2026 en TWS. Esto valida la fuente, no una entrada ni la rentabilidad.
- Pine FAST v2.2 conserva versión y reglas; se agrega únicamente `current_contract` para identificar el vencimiento que TradingView utiliza. Falta actualizar/recrear las dos alertas existentes en TradingView y verificar recepción de ese campo en producción. No se ha hecho desde la aplicación de TradingView.
- Descubierto y corregido un error de sintaxis JavaScript que impedía ejecutar la navegación y temporizadores. Añadida prueba de sintaxis con Node. Verificado cambio de pestañas en navegador de escritorio.
- Límite definido con la política ya existente: el Pine envía una tolerancia máxima de 0,20 ATR desde el disparo, preservando al menos 1,5R bruto al segundo objetivo del plan original (stop 1 ATR, T2 2 ATR). El servidor vuelve a validar matemáticamente el mínimo declarado. No cambia la generación de señales.
- Revisión responsive automatizada a 390 px y 1280 px: cinco vistas navegables, una sola visible, sin desbordamiento horizontal ni errores de navegador. Capturas revisadas para Hoy y Oportunidades. Corregido además el botón Atrás/Adelante del navegador.
- Pendiente: recepción real del identificador y del límite desde las dos alertas recreadas en TradingView, seguida por una prueba integral alerta→cotización→clasificación. El navegador aislado disponible no comparte la sesión de TradingView del usuario. No cerrar etapas 1–2 ni iniciar etapas 3–6 como si estuvieran terminadas.

## Etapa 3 — centro diario de gestión por posición

Implementado el 4 de septiembre de 2026:

- Cartera abre con una única «Primera decisión de cartera», tomada de la misma cola priorizada del motor; no crea ni modifica recomendaciones.
- La prioridad muestra ticker, acción principal, motivo y momento de revisión, con acceso directo a la posición correspondiente.
- Las posiciones se ordenan en Actuar ahora, Revisar hoy, Mantener y Actualizar datos.
- Filtros operativos y búsqueda por ticker trabajan juntos; el operador puede aislar cada cola sin recorrer todas las tarjetas.
- Cada posición conserva recomendación principal, motivo, condición que cambiaría el plan, vínculo con la entrada detectada, estructura económica, alternativas y confirmación de revisión.
- La vista móvil apila la prioridad y mantiene accesibles los controles sin desbordamiento.

Validación: 661 pruebas automáticas satisfactorias. La etapa 3 queda implementada; falta comprobarla visualmente con la cartera real instalada. Las etapas 4–6 permanecen pendientes.

## Etapa 4 — oportunidades separadas por estrategia

Implementado el 4 de septiembre de 2026:

- El centro de Oportunidades tiene filtros independientes para Futuros, CANSLIM, RSP, Earnings CANSLIM y puts SPY/RSP de 120–150 días.
- Earnings y puts largos muestran su avance de datos, evidencia acumulada, faltantes y siguiente paso dentro del flujo diario.
- Ambas estrategias nuevas permanecen inequívocamente como `RESEARCH_ONLY`: no pueden aparecer como entrada lista, usar simulador de capital, consumir capacidad ni generar una orden.
- Historial conserva el detalle de investigación y ahora tiene un destino directo desde sus tarjetas.
- La vista móvil acomoda el quinto estado «En investigación» sin mezclarlo con bloqueos operativos.

La etapa 4 queda implementada a nivel de experiencia y seguridad. Convertir cualquiera de estas estrategias en operable requerirá una decisión posterior sustentada en muestra y validación; no forma parte de esta etapa. Las etapas 5–6 permanecen pendientes.

## Etapa 5 — apertura y ciclos automáticos verificables

Implementado el 5 de septiembre de 2026:

- Confirmada la instalación real en macOS de apertura/publicación automática cada hora de 07:35 a 13:35 CDMX en días hábiles, además de preflight, preparación de mercado, monitor postapertura y vigilancia del entorno.
- Hoy muestra un bloque visible de Apertura automática con estado, último reporte confirmado, último intento del programador y próxima ejecución.
- La consola distingue expresamente «intento» de «ciclo confirmado». Si macOS intentó ejecutar el trabajo y no apareció un reporte posterior, lo eleva a revisión en lugar de mostrar un falso estado correcto.
- En mercado cerrado conserva la última evidencia y muestra la siguiente ejecución hábil sin exigir una apertura manual.
- El botón manual permanece como recuperación cuando TWS estaba cerrado o el ciclo programado terminó con pendientes.

La etapa 5 queda implementada. Falta la etapa 6: revisión integral de Actividad/aprendizaje, recorrido visual final y cierre de inconsistencias residuales.

Validación: 665 pruebas automáticas satisfactorias y comprobación del panel servido por la consola permanente. En la lectura real del 5 de septiembre, el último intento del programador era posterior al último reporte confirmado; por diseño la consola lo mostró como revisión pendiente, no como éxito.

## Etapa 6 — actividad, rutina y auditoría visual final

Implementado el 5 de septiembre de 2026:

- Auditoría estructural de la consola instalada: cinco vistas válidas, sin identificadores duplicados y sin enlaces internos rotos.
- Actividad abre con la conclusión del aprendizaje y el tamaño de muestra antes de mostrar señales vencidas o informes técnicos.
- Hoy incorpora «Mi rutina diaria» con cuatro pasos: leer Hoy, proteger la cartera, evaluar entradas realmente listas y cerrar/aprender.
- La rutina enlaza directamente con cada zona y mantiene explícito que la consola nunca envía órdenes.
- Revisión visual real en Safari de Hoy, Oportunidades y Actividad. La jerarquía, estados, filtros y estrategias de investigación se distinguen correctamente.
- Corregido ruido residual: el simulador de capital sólo aparece para una oportunidad `ENTRY_READY`; una idea en preparación o espera ya no presenta controles prematuros de tamaño.

La reingeniería visual acordada en las etapas 1–6 queda implementada. La validación de funcionamiento económico y de alertas reales continúa siendo observación de mercado, no una tarea visual ni una garantía de rentabilidad.

Validación final de código: 667 pruebas automáticas satisfactorias.

Corrección posterior de auditoría cerrada con mercado cerrado: el panel ya lee el último sobre completo del programador (`DONE`/error) y no usa por sí sola la hora de modificación del log. Esto evita marcar como fallido un ciclo correcto cuyo archivo terminó de escribirse después de generar el reporte.

## Fase posterior — operación ultrarrápida y validación de uso

- Añadido **Modo foco** persistente: reduce Hoy a la decisión principal y sus cinco lecturas esenciales, ocultando preparación, rutina expandible y cierre mientras el operador necesita velocidad.
- Añadidos expedientes automáticos por ticker en Actividad: decisión → ejecución detectada/informada → gestión → resultado. La aparición de una posición en IBKR crea el vínculo operativo; un fill exacto continúa requiriendo confirmación del broker.
- Añadida telemetría mínima exclusivamente local: vista visitada, activación del modo foco y hora. No registra cuentas, posiciones, precios ni órdenes.
- Actividad muestra avance hacia 5–10 sesiones reales y evita recomendar más simplificación antes de contar con una muestra de uso.

Validación técnica: 670 pruebas automáticas satisfactorias; endpoint local de telemetría comprobado sin datos financieros y primera sesión de validación iniciada.
