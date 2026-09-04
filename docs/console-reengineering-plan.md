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
