# Auditoría de experiencia de usuario de Ultimus

Fecha: 7 de septiembre de 2026. Alcance: consola local instalada, recorridos principales, presentación de decisiones y código que los implementa.

## Dictamen

Ultimus tiene una base funcional amplia: priorización, posiciones agrupadas, filtros, vigilancia de señales, restricciones de investigación y seguimiento. La mejora de mayor impacto consiste en lograr que **cada pantalla conduzca a una decisión comprensible, coherente y verificable**.

Actualmente el usuario todavía debe reconciliar mensajes de distintos módulos, interpretar códigos internos y buscar el siguiente paso. La estética ya permite trabajar; la coherencia entre estados, cuentas, recomendaciones y acciones necesita atención antes de añadir más paneles.

Esta revisión identifica **20 hallazgos**: ocho de prioridad alta, ocho de prioridad media y cuatro mejoras de producto/validación. No son veinte fallos equivalentes: se distingue evidencia observada, reproducción aislada, inspección de código y propuesta de diseño.

## Alcance y evidencia

- Recorrido real por Hoy, Cartera, Oportunidades, Actividad y Más en `http://127.0.0.1:8765/console`.
- Apertura del detalle prioritario de MNQ y prueba de filtros y enlaces CANSLIM.
- Inspección visual en escritorio de 1280 × 720 y de Hoy a 390 × 844. La comprobación móvil es parcial, no una certificación de todos los flujos.
- Lectura del código de consola, pruebas relevantes, guía y auditoría/reingeniería anteriores. No se auditó exhaustivamente cada motor matemático ni seguridad, dependencias o despliegue.
- El archivo de consola del proyecto y el instalado tienen el mismo SHA-1: `363616559308a310566dad0d36fc73bbf890d9a1`.
- Se ejecutaron las **39 pruebas** de `tests/test_console_service_and_ux.py`: todas satisfactorias. No se volvió a ejecutar la suite completa ni se da por revalidada la cifra histórica de 670 pruebas.
- Reproducciones aisladas del envío de formulario, calendario, clasificación de expediente y persistencia de tareas atendidas.
- No se pulsaron acciones operativas reales, no se enviaron órdenes ni notificaciones, ni se cambiaron reglas o código de producción. La navegación puede añadir eventos a la telemetría local existente: no debe contarse como una sesión humana de validación.

Los importes y estados observados describen una captura temporal de la interfaz; no validan la exactitud económica de las fuentes ni constituyen instrucciones de inversión.

## Prioridad alta: corregir coherencia y funcionamiento

### 1. Los botones de tareas pueden perder la acción al enviarse

**Evidencia:** `render_command_center` usa botones con `name="task_action"`. El manejador general conserva explícitamente sólo el botón con `name="action"` y después desactiva todos los botones antes del envío. El servidor exige `task_action`.

Se reprodujo con el mismo manejador en una página temporal, con datos ficticios y envío GET: pulsar “Marcar atendido” produjo `/result?task_id=TASK-TEST`, sin `task_action=DONE`. El 404 posterior correspondía al destino ficticio, no al problema que se buscaba. No se alteró el diario real. La misma construcción afecta a Revisar y Posponer.

**Impacto:** una acción cotidiana puede terminar en error aunque el usuario haya hecho lo correcto.

**Mejora:** capturar nombre y valor del botón pulsado antes de desactivarlo; unificar el envío de formularios. Mostrar confirmación junto a la tarea, con opción de deshacer cuando corresponda.

**Aceptación:** probar los tres botones desde navegador y verificar que el servidor recibe la acción correcta; la tarea cambia al estado esperado una sola vez.

**Código:** `scripts/ibkr_account_profile.py:3403`, `:11175`, `:11214`, `:11957`.

### 2. Abrir detalle de CANSLIM devuelve a Hoy

**Evidencia observada:** Oportunidades → Todas → tarjeta MU → Abrir detalle. La URL cambia a `#canslim-radar`, pero la vista visible es Hoy. El mapa `targetViews` no incluye `canslim-radar`; `hashchange` cae en Hoy.

**Mejora:** resolver cada destino con su vista contenedora y abrir el activo seleccionado, no sólo un radar genérico.

**Aceptación:** los enlaces de MU, AMD y NVDA abren su detalle en Oportunidades; funcionan también URL directa, recarga y Atrás/Adelante. Verificar que el destino exista no basta: debe estar visible.

**Código:** `scripts/ibkr_account_profile.py:6477`, `:10986`.

### 3. El estado de mercado ignora festivos y usa horario UTC fijo

**Evidencia observada:** Hoy muestra “Abierto” el 7 de septiembre de 2026. NYSE está cerrado por Labor Day, según su [calendario oficial](https://www.nyse.com/publicdocs/nyse/ICE_NYSE_2026_Yearly_Trading_Calendar.pdf).

`is_us_market_session_now` sólo excluye fines de semana y acepta 13:30–20:00 UTC. Una reproducción con la fecha fijada al 7 de septiembre a las 15:00 UTC devuelve `True`. `next_us_market_open` tampoco contempla festivos.

**Impacto:** el usuario puede interpretar una espera normal como avería, esperar una evaluación que no corresponde o confiar en una etiqueta de sesión incorrecta. También hay riesgo de una hora de desfase en invierno.

**Mejora:** un calendario por mercado e instrumento, zona `America/New_York`, festivos, cierres anticipados y horarios específicos de futuros. Separar “próxima actualización del sistema” de “próxima sesión de negociación”. El cierre de NYSE no permite inferir que todos los futuros estén cerrados.

**Aceptación:** escenarios de festivo, sesión normal, invierno/verano y cierre anticipado; etiquetas específicas para acciones/opciones y futuros.

**Código:** `scripts/ibkr_account_profile.py:1561`, `:2932`, `:3518`.

### 4. RSP hereda capacidad general sin identificar su cuenta

**Evidencia observada:** la tarjeta RSP presenta capacidad disponible de $19,582.12; el panel específico identifica la cuenta retiro y muestra fondos de $4,328.66 y poder de compra de $17,314.63. La tarjeta no explica el alcance del importe.

**Código:** el centro calcula una sola `available_capacity` y la aplica a todos los elementos, incluido RSP y su simulador. La estrategia RSP está asignada a retiro.

**Impacto:** confundir recursos de distintas cuentas. En la captura RSP estaba bloqueada; no se observó una entrada real habilitada indebidamente. Sin embargo, la misma variable participa en la proyección y la clasificación por capacidad.

**Mejora:** cada oportunidad debe llevar cuenta, moneda, fuente, hora y tipo de capacidad; resolver fondos de la cuenta asignada. No intercambiar fondos disponibles, poder de compra y margen.

**Aceptación:** con dos cuentas de capacidad distinta, RSP usa sólo retiro en tarjeta, detalle y simulación; ninguna pantalla sugiere transferibilidad de fondos.

**Código:** `scripts/ibkr_account_profile.py:6140`, `:6367`, `:6399`, `:4690`.

### 5. “Actuar ahora” y “Mantener y monitorear” compiten dentro de una posición

**Evidencia observada:** MNQ es la decisión principal “Actuar ahora”; al abrirla, “Recomendación del motor” dice “Mantener y monitorear” y que no existe un disparador determinista para cambiar la posición.

La cola clasifica como urgente por coincidencias de palabras como `RISK` o por la presencia de bloqueadores. La alternativa principal se obtiene de otra estructura.

**Interpretación:** revisar con urgencia y mantener pueden ser compatibles, pero la interfaz no explica esa relación; el usuario recibe dos aparentes instrucciones.

**Mejora:** separar **prioridad de revisión** de **acción sobre la posición**. Ejemplo de redacción, sujeto al diagnóstico del motor: “Revisar exposición conjunta hoy. Plan actual: mantener. No hay ajuste confirmado”. Una misma conclusión debe alimentar Hoy, Cartera y detalle.

**Aceptación:** cada posición presenta una acción principal, una urgencia justificada y el cambio concreto que haría revisar el plan. Los bloqueos de datos no se traducen automáticamente en modificar exposición.

**Código:** `scripts/ibkr_account_profile.py:7854`, `:7572`, `:7595`.

### 6. Una posición abierta puede aparecer como resultado histórico cerrado

**Evidencia observada:** NFLX y TLT están en Cartera y aparecen en Actividad como “Resultado registrado”. El expediente se agrupa sólo por ticker y prioriza cualquier resultado histórico no pendiente sobre una posición actual. Una reproducción ficticia con posición abierta y resultado anterior devuelve fase `closed`.

**Mejora:** identificar cada operación/ciclo por cuenta, instrumento/contrato y ciclo de entrada. Mostrar “Posición actual” y “Operaciones anteriores” por separado. Si falta vínculo, usar “Sin vincular” y evitar atribuirle el resultado de otra operación.

**Aceptación:** dos operaciones del mismo ticker, incluida una ya cerrada, conservan estados y resultados independientes. Las posiciones de dos cuentas no se fusionan.

**Código:** `scripts/ibkr_account_profile.py:9443`.

### 7. “Datos vigentes” no explica qué datos están vigentes

**Evidencia observada:** cabecera “Datos vigentes”; Hoy “Datos guardados — Actualizar antes de aumentar riesgo”; RSP con cadena de hace dos días y niveles de hace 25 días.

No necesariamente es un fallo de las fuentes: son ámbitos distintos que la pantalla presenta como un estado global.

**Mejora:** estado por decisión: “Cuenta actualizada / evaluación remota pendiente / RSP necesita cadena”. Mostrar última observación útil y consecuencia concreta. “Actualizado hace 0 s” debe aclarar si se refiere al informe generado o al dato de mercado subyacente.

**Aceptación:** el usuario puede identificar qué módulo sigue siendo utilizable, cuál requiere actualización y qué acción lo recupera sin abrir diagnóstico técnico.

**Código:** `scripts/ibkr_account_profile.py:2311`, `:2414`, `:3436`.

### 8. Una tarea atendida puede desaparecer durante días aunque siga vigente

**Evidencia de código y reproducción:** `daily_task_view` oculta `DONE` mientras coincida la huella del contenido; no limita ese reconocimiento a la jornada. Un pendiente ficticio marcado atendido el lunes permanece oculto el martes si no cambió el texto.

**Impacto:** “atendido” mezcla haber leído, haber decidido y haber resuelto. Posponer una hora también se ofrece de manera uniforme, sin considerar la ventana útil.

**Mejora:** distinguir “Revisado”, “Mantener bajo vigilancia”, “Ajuste informado” y “Resuelto por evidencia”. Definir caducidad por sesión/condición para la revisión humana; conservar visible el riesgo subyacente. La documentación ya reconoce parte de esta diferencia, pero la acción debe explicarla localmente.

**Aceptación:** una revisión de ayer no silencia una nueva revisión requerida hoy; un riesgo confirmado no desaparece por un reconocimiento; posponer respeta su horizonte.

**Código:** `scripts/ibkr_account_profile.py:3280`, `:3311`.

## Prioridad media: reducir esfuerzo y ambigüedad

### 9. Español incompleto en las decisiones más importantes

Se observan razones en inglés, `FUTURES_RATIO_CALENDAR_SPREAD`, `NO DATA`, `HIGH`, `OPEN`, `WAIT_DATA`, `UNKNOWN` y códigos de faltantes históricos. No están limitados a soporte.

**Propuesta:** catálogo central de términos y mensajes con una explicación breve. Ejemplo: “Falta historial de opciones vencidas” y debajo “La captura diaria continúa; esta estrategia sigue en investigación”. Conservar código original en el detalle técnico. Traducir también días y unidades: “4 días al vencimiento”, “2 contratos vendidos”.

**Aceptación:** ningún código interno aparece como título, motivo o acción principal. Cubrir estados desconocidos con un mensaje útil que no invente una conclusión.

**Código:** `scripts/ibkr_account_profile.py:2742`, `:7176`, `:6340`.

### 10. El filtro de estrategia no delimita el espacio de trabajo

Al seleccionar Futuros (0), desaparecen las tarjetas pero permanecen Radar CANSLIM y Coberturas RSP. Los contadores superiores siguen mostrando el total global sin aclararlo.

**Propuesta:** filtrar toda el área de estrategia o etiquetar explícitamente que el filtro sólo afecta a las tarjetas. La primera opción ofrece un recorrido más directo. Añadir filtros por estado: listas, esperando datos y en seguimiento.

**Aceptación:** Futuros muestra su estado, señales, salud y actividad pertinente. Los contadores indican su alcance. Volver a Todas restaura el conjunto.

**Código:** `scripts/ibkr_account_profile.py:10899`, `:11135`.

### 11. Hoy repite el diagnóstico antes de facilitar la acción

MNQ aparece como titular, primera tarea y elemento para retomar. Las tareas añaden motivos y consecuencias genéricas extensas. El botón más prominente de cabecera sigue siendo “Ejecutar apertura diaria” aunque el sistema tiene automatización.

**Propuesta:** una tarjeta principal con activo, motivo concreto, plan, plazo y **Revisar MNQ**. Bajo ella, dos siguientes prioridades compactas. Actualización automática en una línea; recuperación manual visible cuando es necesaria. Reservar cierre diario para su momento o plegarlo.

**Aceptación:** un usuario identifica su siguiente paso en 10 segundos; alcanza el activo en un clic; no necesita iniciar manualmente un ciclo por la prominencia visual del botón.

### 12. Cartera tarda en llegar a las posiciones

El riesgo global y tres alertas desarrolladas preceden a “Primera decisión de cartera”. Las cifras “6 posiciones”, “6 instrumentos” y “4” estructuras necesitan una nomenclatura común.

**Propuesta:** franja breve de riesgo global, seguida de la posición prioritaria y la lista. Expandir automáticamente sólo un bloqueo crítico pertinente. Mostrar “4 estructuras · 6 instrumentos” y cuenta en cada fila. Conservar el detalle completo del riesgo a un clic.

**Aceptación:** abrir Cartera permite ver la primera posición que requiere revisión sin atravesar alertas de vigilancia; los conteos se reconcilian.

**Código:** `scripts/ibkr_account_profile.py:7930`, `:8660`, `:10880`.

### 13. La espera carece de una explicación operativa específica

Futuros muestra “Esto puede ser una espera normal”; CANSLIM pide esperar una evaluación genérica. El embudo de futuros presenta 0 detectadas, 0 aceptadas y 4 confirmadas sin explicar que pueden proceder de ventanas o fuentes diferentes.

**Propuesta:** diferenciar “Sin señal”, “Sesión cerrada”, “Fuente retrasada” y “Evaluación pendiente”. Explicar qué condición se espera, quién la actualizará y cuándo volver a revisar. Embudos con misma ventana temporal, o grupos separados y etiquetados.

**Aceptación:** cero oportunidades no induce a refrescar compulsivamente; cifras no comparables no se presentan como etapas consecutivas del mismo conjunto.

**Código:** `scripts/ibkr_account_profile.py:6046`, `:6509`.

### 14. Las tarjetas comparten demasiados campos aunque no apliquen

Ideas en preparación e investigación muestran capital, capacidad posterior, riesgo y objetivos con varios N/D. En investigación, “Entrada / nivel” contiene número de eventos y “Objetivo” contiene observaciones acumuladas.

**Propuesta:** tres formatos: oportunidad lista, idea en seguimiento e investigación. La primera explica ticket y riesgo; la segunda condición pendiente; la tercera avance y siguiente hito. Mantener accesibles las cinco estrategias existentes.

**Aceptación:** las etiquetas conservan su significado y ninguna tarjeta de investigación parece una orden incompleta.

**Código:** `scripts/ibkr_account_profile.py:6410`.

### 15. Móvil cabe, pero aún exige demasiado desplazamiento

En Hoy a 390 × 844 no se detectó desbordamiento horizontal. La navegación fija mide aproximadamente 116 px y ocupa tres filas; la acción de la primera tarea queda después del resumen y los cinco indicadores.

**Propuesta:** navegación móvil compacta, resumen de una frase, CTA inmediato y métricas secundarias plegadas. Dar al enlace de revisión una posición alcanzable sin recorrer todo el diagnóstico. Revisar también conservación del foco y texto al actualizar.

**Aceptación:** desde Hoy, el CTA principal es visible sin desplazamiento adicional después de llegar al inicio de esa vista; comprobar 390 px, 320 px y zoom, además de pantallas reales de Cartera/Oportunidades. Esta auditoría sólo verificó visualmente Hoy en móvil.

### 16. Recuperación, formularios y accesibilidad necesitan una misma convención

Existen varias acciones de actualización con alcances diferentes, confirmaciones renderizadas en Hoy y una recarga completa al terminar determinados trabajos. Hay campos visibles sin nombre accesible en riesgo; los filtros usan una clase visual, sin estado `aria-pressed`; los cambios de vista no gestionan explícitamente el foco.

**Propuesta:** botones con alcance claro —“Actualizar precios”, “Actualizar cuenta”, “Reintentar RSP”— y progreso por pasos. Confirmación y error junto al origen, reintento y conservación de campos. Etiquetas asociadas a inputs, estados accesibles y avisos de actualización no invasivos.

**Aceptación:** completar con teclado un recorrido de búsqueda y revisión; lector de pantalla reconoce campos y selección; un error no elimina una nota ni oculta el resultado en otra vista.

**Código:** `scripts/ibkr_account_profile.py:10945`, `:11000`, `:11135`, `:11247`.

## Mejoras de producto y validación

### 17. Actividad debería responder primero “qué cambió para mí”

Actualmente abre con suficiencia estadística y validación de experiencia, después expedientes. Falta un resumen visible de cambios desde la última revisión.

**Propuesta:** “Cambios desde tu última visita”: nueva revisión, dato recuperado, señal vencida y revisión registrada. Filtros por fecha, cuenta, activo y tipo. Aprendizaje e investigación siguen disponibles en apartados propios. Evitar recomendaciones de cambios de parámetros sin evidencia.

### 18. La medición actual no demuestra usabilidad

“Sesiones” cuenta fechas únicas, no sesiones completas ni tareas exitosas. Un clic en navegación puede registrar `VIEW_CHANGE` tanto desde el manejador del enlace como desde el manejador delegado. La auditoría automatizada también añade visitas. La vista más visitada puede ser la más confusa, no la más útil.

**Propuesta:** excluir QA y medir, localmente y sin datos financieros, inicio/fin de tarea, errores y tiempo hasta el detalle. Validar comprensión con observación humana. Cinco días de visitas no equivalen a una experiencia validada.

**Aceptación:** eventos sin duplicación; sesiones humanas distinguibles de QA; evidencias de tarea completada, no sólo de páginas abiertas.

**Código:** `scripts/ibkr_account_profile.py:1283`, `:9511`, `:11000`.

### 19. La arquitectura favorece pequeñas divergencias entre pantallas

La consola reúne 12,224 líneas en un archivo: servicios, reglas de presentación, HTML, estilos, JavaScript y rutas. Cabecera, cola, alternativas y expedientes interpretan estados de forma separada.

**Propuesta técnica al servicio de UX:** un modelo de presentación compartido por decisión con identidad, cuenta, recomendación, prioridad, evidencia, vigencia y siguiente acción. Separar gradualmente navegación, mensajes y componentes. No es necesario reescribir la aplicación ni cambiar de framework para empezar.

**Aceptación:** el mismo caso produce la misma conclusión en todas las vistas; la presentación no vuelve a inferir riesgo mediante búsqueda de palabras.

### 20. Las pruebas deben validar recorridos y significado

Las 39 pruebas de UX pasan y muchas verifican cadenas presentes o estructuras generadas. Eso no detectó el enlace que cambia a una vista equivocada ni el botón que pierde su acción.

**Propuesta:** añadir escenarios de navegador y contratos entre vistas, con datos sintéticos y sin actuar sobre el diario real. Conservar las pruebas útiles actuales. La auditoría previa es evidencia histórica, no sustituto de validar el comportamiento actual.

**Aceptación:** al menos los recorridos y escenarios descritos abajo deben fallar si reaparecen los hallazgos de prioridad alta.

## Experiencia objetivo

| Vista | Pregunta que resuelve | Primer contenido | Acción principal |
|---|---|---|---|
| Hoy | ¿Qué debo revisar primero? | Una decisión, motivo concreto y plazo | Revisar ese caso |
| Cartera | ¿Qué cambió en mis posiciones? | Prioridad y lista por estructura/cuenta | Abrir gestión |
| Oportunidades | ¿Hay algo evaluable para esta cuenta? | Estado y estrategia seleccionada | Revisar entrada o condición pendiente |
| Actividad | ¿Qué ocurrió desde mi última revisión? | Cambios y acciones registradas | Retomar caso |
| Configuración | ¿Qué conexión o cuenta debo ajustar? | Sólo componentes que requieren atención | Resolver componente |

Cada caso debería mostrar: **activo y cuenta → plan actual → por qué → cuándo revisar → condición que cambia el plan → acción**. La evidencia técnica se despliega desde ahí.

## Orden recomendado de implementación

1. **Funcionamiento y confianza:** formularios, enlaces, calendario y capacidad por cuenta (hallazgos 1–4). Añadir sus regresiones de navegador y datos sintéticos.
2. **Una conclusión por caso:** prioridad frente a acción, identidad de operaciones, vigencia de datos y revisiones (5–8). Contrastar Hoy, Cartera y Actividad con los mismos escenarios.
3. **Flujo diario más corto:** lenguaje, CTA, filtros de alcance completo, formatos por estado y móvil (9–16). Mantener los motores y compuertas existentes.
4. **Validación humana y evolución:** cambios recientes, medición corregida y separación gradual de componentes (17–20).

No conviene empezar por colores, gráficos adicionales o un asistente conversacional que explique estados todavía inconsistentes. Primero estabilizar lo que la consola afirma y lo que sus botones hacen.

## Plan de aceptación con usuarios

Usar escenarios controlados; los tiempos son objetivos propuestos, todavía no resultados medidos.

| Tarea | Criterio de éxito |
|---|---|
| Abrir Hoy | Identificar prioridad y siguiente paso en ≤10 segundos |
| Abrir una prioridad | Llegar al caso exacto en un clic, conservando cuenta/contrato |
| Evaluar “Actuar ahora” + mantener | Explicar correctamente que revisión no implica modificar la posición |
| Revisar RSP | Identificar cuenta, fondos y vigencia sin consultar otro panel |
| Filtrar Futuros sin señal | Explicar si se espera mercado, señal o datos, y la siguiente revisión |
| Marcar revisado y regresar mañana | Confirmación clara y reaparición conforme a la política de revisión |
| Consultar ticker con operación cerrada y abierta | Distinguir ambos ciclos y sus resultados |
| Recuperar actualización fallida | Entender qué falló y reintentar sin perder el contexto |
| Navegar en móvil/teclado | Encontrar CTA, reconocer filtros y mantener foco legible |

Incluir festivo, invierno, cierre anticipado, fuente retrasada, dos cuentas, cero oportunidades, señal caducada durante la revisión y operación repetida en el mismo ticker. Comparar errores, tiempo y comprensión antes/después. La validación de experiencia no valida rentabilidad.

## Qué conservar

La navegación de cinco vistas, las estructuras agrupadas, los filtros de cartera, la distinción de estrategias en investigación, los controles de vigencia de futuros y el acceso al detalle técnico son una buena base. La propuesta los hace más coherentes y fáciles de usar; no requiere añadir complejidad operativa.
