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
