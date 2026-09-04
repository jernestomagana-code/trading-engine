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

Pendiente dentro de etapas 1–2: validar precios actuales y límites de persecución, y evaluación visual de escritorio/móvil. No se han implementado todavía las etapas 3–6.

No cambiar criterios de entrada ni habilitar estrategias RESEARCH_ONLY como parte del rediseño visual. No confundir comprobaciones técnicas satisfactorias con validación de rentabilidad.
