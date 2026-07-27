# Guía de uso de Stock Ultimus Console

Esta guía explica cómo quedó funcionando la consola, qué significa cada bloque y cómo operarla de forma segura. Está escrita para el operador; no hace falta conocer el código del proyecto.

**Documento oficial del proyecto:** la consola muestra directamente este archivo mediante el botón **Ayuda**. Toda modificación que agregue, quite o cambie una sección, estado, botón o flujo operativo debe actualizar también esta guía. Las validaciones automáticas comprueban que las secciones principales de navegación continúen documentadas.

## 1. Qué es la consola

Stock Ultimus Console es el centro de lectura, revisión y seguimiento de la operación. Reúne en una sola pantalla:

- el estado del sistema y de sus conexiones;
- las alertas que merecen revisión;
- las posiciones detectadas en el broker;
- el riesgo por cuenta y de la cartera consolidada;
- simulaciones de estrés y rebalanceo;
- resultados, aprendizaje y mantenimiento;
- herramientas administrativas de uso ocasional.

La consola **no compra, vende, abre, cierra ni modifica órdenes automáticamente**. Analiza, prioriza, registra y recomienda el siguiente paso. Toda decisión y ejecución real continúa siendo manual en IBKR/TWS.

## 2. Cómo está formada

```text
Fuentes de información
  IBKR/TWS + TradingView + producción + archivos locales
                         │
                         ▼
              Motor Stock Ultimus
  alinea datos, valida calidad, calcula riesgo y prioriza
                         │
                         ▼
              Stock Ultimus Console
  Inicio → Pendientes → Riesgo → Posiciones → RSP
                 → Análisis → Administración → Ayuda
                         │
                         ▼
                 Revisión humana
            decisión y operación manual en IBKR
```

La consola vive en tu Mac y abre en `http://127.0.0.1:8765/console`. El servicio se inicia automáticamente al entrar a tu sesión de macOS y vuelve a levantarse si el proceso se interrumpe. El archivo **Stock Ultimus Console.command** sirve como acceso directo y también como recuperación si el servicio permanente no estuviera disponible.

## 3. Cómo abrirla

1. Abre **Stock Ultimus Console.command**.
2. La consola debe aparecer en el navegador.
3. Si ya estaba funcionando, simplemente se abre; no inicia una segunda instancia.
4. Para leer datos nuevos del broker, TWS o IB Gateway debe estar abierto, desbloqueado y con acceso API habilitado.

El navegador puede cerrarse sin apagar el servicio. Volver a abrir el acceso directo recupera la misma consola.

## 4. La ruta rápida de cada día

Ésta es la rutina recomendada para no perderse entre las funciones avanzadas.

### Antes de mercado o al comenzar la jornada

1. Abre TWS/IB Gateway y confirma que la sesión esté desbloqueada.
2. Abre la consola.
3. Mira primero el estado de conexión superior.
4. Cuando tengas una nueva lectura de niveles/gamma, guárdala desde **RSP → Actualizar lectura de mercado RSP**.
5. Presiona **Ejecutar apertura diaria**. El ciclo valida el contexto RSP guardado y consulta una cadena RSP independiente de 7–14 DTE.
6. Espera a que el proceso muestre `DONE`. No vuelvas a presionar el botón mientras esté trabajando.
7. Lee **Inicio** y sus **Pendientes priorizados**.
8. Sigue el orden propuesto por la consola: **Riesgo**, **Posiciones**, **RSP** y después oportunidades/alertas.

La apertura puede tardar varios minutos porque el refresh principal y el refresh específico de RSP son procesos separados. Mientras la consola muestre que está trabajando, no inicies una segunda apertura.

Durante la apertura, el puente reúne primero precios, posiciones y contratos en el entorno local. La publicación se realiza después como un snapshot consolidado; así una respuesta lenta de producción no detiene cada contrato individual.

### Durante la sesión

1. Usa **Actualizar** para releer producción y buscar alertas nuevas.
2. Si las posiciones o la capacidad se ven viejas, usa **Refresh posiciones IBKR**.
3. Revisa primero alertas `RISK`, luego `ACTION` y después `WATCH`.
4. Registra lo que hiciste con los botones de cada alerta o posición.
5. Ejecuta cualquier operación real exclusivamente de forma manual en TWS.

### Al cierre

1. Verifica que las alertas atendidas tengan un estado registrado.
2. Actualiza el seguimiento de resultados.
3. Revisa el reporte ejecutivo y los pendientes.
4. No interpretes resultados incompletos como evidencia estadística definitiva.

### Fuera de horario o en fin de semana

`Fuera de mercado`, `Esperando mercado` o `WAIT_MARKET` pueden ser estados normales. No significan que el sistema esté dañado y tampoco son una autorización para entrar a una operación.

## 5. Franja superior: salud y control

Este es el primer bloque que debe leerse.

### El semáforo

- **Verde:** las piezas principales están alineadas para revisar la operación.
- **Ámbar:** la consola funciona, pero hay datos, procesos o revisiones pendientes.
- **Rojo:** existe un bloqueo importante. No se debe confiar en una lectura operativa hasta resolverlo.

El color no es una señal de compra o venta. Indica la salud operativa de la consola.

### Los cuatro indicadores visibles

| Indicador | Qué significa | Si aparece `NO` o pendiente |
|---|---|---|
| Producción | La consola puede leer el estado protegido del motor publicado. | Usa **Actualizar estado**; si persiste, revisa conexión o acceso. |
| IBKR | Hay evidencia de conexión local con TWS/IB Gateway. | Abre/desbloquea TWS y usa **Validar IBKR**. |
| Datos | Existe un paquete local de datos para evaluar. | Ejecuta **Ejecutar apertura diaria** o un refresh de IBKR. |
| Capacidad | Hay datos de capital, margen y disponibilidad de la cuenta. | Actualiza IBKR antes de evaluar tamaño o viabilidad. |

Las acciones técnicas de conexión y publicación quedaron dentro de **Más opciones** para no competir con la apertura diaria.

### Botones rápidos

| Botón | Para qué sirve | Qué no hace |
|---|---|---|
| Ejecutar apertura diaria | Ejecuta CANSLIM, evalúa dinámicamente hasta 14 subyacentes con opciones, refresca IBKR y RSP 7–14 DTE, publica, prepara contexto conservador de futuros, reconcilia señales y genera el reporte. | No autoriza órdenes ni da por validado el contexto macro. |
| Actualizar | Relee producción, GPT y alertas. | No cambia cuenta y no consulta profundamente IBKR. |
| Validar conexión IBKR | Dentro de **Más opciones**; prueba TWS/API, cuenta y capacidad. | No hace un escaneo profundo de opciones. |
| Alinear contexto publicado | Dentro de **Más opciones**; corrige la cuenta y el contexto que ve GPT. | No sustituye un refresh completo de opciones. |

Cuando aparezca **La consola está trabajando**, espera. Lanzar varios refresh simultáneos sólo duplica carga y dificulta interpretar qué resultado es el más reciente.

## 6. Navegación principal

La barra fija permite saltar directamente a:

1. **Inicio**
2. **Pendientes**
3. **Riesgo**
4. **Posiciones**
5. **RSP**
6. **Análisis**
7. **Administración**
8. **Ayuda**

Los primeros cinco destinos forman el flujo diario. **Análisis** y **Administración** permanecen cerrados y se abren sólo cuando hacen falta. Las alertas técnicas completas continúan disponibles desde el panel secundario **Alertas y diagnósticos**.

## 7. Inicio y Pendientes

**Inicio** combina en una sola verdad el estado de conexión, riesgo consolidado, posiciones, RSP, alertas y última apertura. Ya no usa únicamente el conteo de un motor aislado.

**Pendientes priorizados** convierte esas fuentes en una cola única. Cada elemento indica área, motivo y enlace **Revisar**. El orden es:

1. riesgo crítico o alto;
2. posiciones con asignación, defensa o revisión;
3. RSP con lectura/cadena/capacidad pendiente;
4. alertas u oportunidades con calidad suficiente.

| Modo | Significado | Conducta recomendada |
|---|---|---|
| Monitoreo | No hay bloqueo ni alerta prioritaria inmediata. | Actualizar estado periódicamente. |
| Revisión | Hay una o más alertas `ACTION`. | Revisar checklist, contrato, riesgo y capacidad. |
| Riesgo | Hay alertas `RISK`. | Atenderlas antes de estudiar nuevas entradas. |
| Procesando | Hay una tarea local en ejecución. | Esperar `DONE`; no repetir el refresh. |
| Esperando mercado | El sistema espera una sesión o evento válido. | Mantener monitoreo; no convertirlo en entrada. |
| Fuera de mercado | La sesión estadounidense está cerrada. | Preparar y diagnosticar, no forzar datos de mercado. |
| Bloqueado | Falta una conexión, credencial o dato esencial. | Resolver el bloqueo antes de operar. |
| Acumulando evidencia | La apertura técnica terminó, pero faltan eventos reales o resultados cerrados para confiar en `ENTRY_READY`. | Mantener seguimiento y no cambiar parámetros todavía. |

Las cuatro lecturas rápidas muestran **Riesgo**, **Posiciones**, **RSP** y **Mercado**. **Última apertura** informa si el ciclo técnico terminó; el avance de evidencia estadística permanece separado dentro de Análisis.

## 8. Alertas y diagnósticos

Este panel permanece cerrado cuando no hay una señal operable. La consola separa:

- **Alertas Operables:** configuraciones con suficiente calidad para revisión humana.
- **Futuros Intradía:** señales nativas de MNQ/MES y señales Chris IA de USTEC.F/US500F recibidas desde TradingView.
- **Diagnóstico oculto:** casos con datos insuficientes, espera, bloqueo o calidad baja.
- **Ya revisadas/en seguimiento/cerradas:** historial operativo reciente.

Que una alerta aparezca como operable significa **“revisar ahora”**, no “ejecutar ahora”.

La configuración productiva de TradingView contiene **7 alertas consolidadas**:
`MNQ1!` y `MES1!` en 5 minutos; `QQQ` y `SPY` en 15 minutos; `VIX` en diario;
y Chris IA para `USTEC.F` y `US500F` en 15 minutos. Todas usan
`Any alert() function call` y publican en `/technical_snapshot`. Tus alertas
personales pueden coexistir, pero no cuentan dentro de esas siete. El inventario
detallado y su procedimiento de validación están en
`docs/tradingview-production-active-alerts.md`.

Las señales de futuros siguen una ruta protegida contra pérdidas: TradingView confirma la recepción rápidamente, el motor guarda y notifica en segundo plano y, si hubo un reinicio, la apertura diaria reconcilia el registro permanente con la bandeja operativa. Una señal pendiente reciente debe aparecer en **Futuros Intradía** aunque no forme parte del ranking normal de acciones u opciones.

La apertura crea, sólo cuando no existe uno, un contexto premercado **automático conservador**. Este evita que una señal quede sin expediente de sesión, pero mantiene macro, volatilidad y referencias en `NEEDS_REVIEW`; debes validarlos en la consola antes de aprobar una entrada. El motor también toma automáticamente de la publicación vigente el valor neto de la cuenta para calcular riesgo cuando TradingView no lo incluye. Un valor recibido directamente en la alerta siempre tiene prioridad.

El bloque distingue actividad de oportunidad. **Recibidos hoy** confirma que el enlace funcionó; **Aceptados hoy** excluye lo enviado a cuarentena; **WATCH** significa radar sin entrada; **snapshots** son pulsos de sesión; **Entradas hoy** cuenta candidatos ENTRY aunque ya hayan vencido; y **Motor diario** confirma que fueron incorporados a la evaluación. Si recibió futuros pero el motor procesó cero, muestra **PIPELINE_MISMATCH**: es una incidencia técnica, no una sesión sin oportunidades. Sólo una ENTRY o RISK todavía vigente se eleva como tarjeta principal; los WATCH no deben saturar la bandeja del operador.

### Severidades

| Severidad | Interpretación |
|---|---|
| ACTION | Merece una revisión manual completa. |
| RISK | Existe un bloqueo o una condición de riesgo; tiene prioridad. |
| WATCH | Mantener en observación; todavía no está lista. |
| INFO | Información o diagnóstico, normalmente no accionable. |

### Estados frecuentes

| Estado | Significado |
|---|---|
| ENTRY_READY | Pasó las puertas automáticas disponibles; aún exige revisión manual. |
| MANUAL_REVIEW | Requiere juicio del operador antes de cualquier decisión. |
| WAIT_MARKET | Espera sesión o confirmación real de mercado. |
| WAIT_TECHNICAL | Falta confirmación técnica válida. |
| WAIT_OPTIONS_DATA | Faltan datos completos del contrato, griegas, spread o DTE. |
| WAIT_ACCOUNT_CONTEXT | Falta alinear la cuenta o su capacidad. |
| RISK_BLOCKED | La configuración está bloqueada por riesgo; no es accionable. |
| NO_DATA | No existe evidencia suficiente para emitir una decisión. |

### Qué contiene una tarjeta

- ticker, estrategia, severidad y estado;
- contrato seleccionado: vencimiento, strike, DTE, bid/ask, mid, delta y spread;
- economía estimada: prima, capital requerido y capacidad disponible;
- vigencia y edad de la alerta;
- motivo de aparición y bloqueo principal;
- checklist de Score, Técnico, Opciones, Volatilidad, Capacidad, CANSLIM y Riesgo.

Un punto pendiente en el checklist no debe ignorarse. Si falta contrato, capacidad o validación de riesgo, la alerta no está completa.

En una tarjeta de **Futuros Intradía**, la información cambia para evitar conceptos de opciones que no aplican. Muestra evento, dirección, entrada, stop, TP1/TP2, relación riesgo/beneficio, contratos permitidos y los estados de construcción, riesgo, portfolio y contexto pre-market. Usa **Visto**, **Revisando**, **Watch**, **Rechazar** o **Cerrar** para registrar qué hiciste; esos botones nunca envían una orden.

El celular está reservado exclusivamente para **ENTRY**. La alerta es deliberadamente breve: **activo y dirección**, **precio de disparo**, **stop**, **Target 1**, **Target 2** y una sola acción recomendada. Para acciones y opciones se exige `ENTRY_READY`; en futuros se exige un evento de entrada que no haya sido degradado a `WATCH_ONLY`. WATCH, REBOTE, RISK, resúmenes, nudges, postcierre e incidencias técnicas permanecen visibles en la consola, pero no generan Pushover. Cuando TradingView confirma una entrada pero no envía niveles, el motor calcula referencias provisionales con ATR: stop a 1 ATR, Target 1 a 1R y Target 2 a 2R. El mensaje las etiqueta como **estimadas por ATR** y exige confirmarlas en la consola; nunca debe interpretarse como una orden automática ni reemplaza el límite de riesgo del operador.

Para conservar ese filtro, las siete alertas del proyecto mantienen el webhook
activo y `Notify in app` apagado dentro de TradingView. No actives el push móvil
directo de TradingView: ese canal no conoce la clasificación final del motor y
podría enviar WATCH, REBOTE o diagnósticos al teléfono.

Antes de enviar una ENTRY, el motor aplica una puerta adicional de calidad direccional. Compara la dirección con tendencia, votos multitemporales, MACD, RSI y cruce estocástico. Si una entrada va contra tendencia o contra la mayoría MTF necesita al menos tres confirmaciones y no puede acumular tres o más conflictos. Si no las reúne queda como **WATCH_ONLY**: permanece visible únicamente en la consola y no produce aviso móvil. La tarjeta muestra **confirmaciones a favor**, **conflictos**, calificación de la puerta y motivo del bloqueo.

TradingView mantiene tres niveles para no perder oportunidades: **WATCH** detecta el giro inicial, **REBOTE** identifica un patrón fuerte pero contra tendencia o contra la mayoría MTF, y **ENTRY** queda reservado para una señal alineada. Los tres llegan al registro y a la consola. Sólo ENTRY confirmada produce una notificación móvil.

El `score` de TradingView mide cuánto coincide la lectura con las reglas internas de ese patrón; **no es una probabilidad de éxito**. Por eso una reversión puede tener score 100 y aun así quedar en WATCH si el mercado continúa alineado en sentido contrario. La consola corrige además el indicador `counter_trend` usando la tendencia y los votos MTF, aunque la fuente lo haya enviado de forma inconsistente.

### Botones de seguimiento de alertas

| Botón | Úsalo cuando… |
|---|---|
| Visto | Sólo confirmaste que leíste la alerta. |
| Revisando | Estás haciendo la revisión manual. |
| Watch | Decidiste seguir observándola. |
| Paper | La seguirás como operación simulada. |
| IBKR aplicada | Ejecutaste manualmente en IBKR y registrarás fill y cantidad. No ejecuta la orden. |
| No aplicada | Decidiste no ejecutarla en IBKR. |
| Missed | La oportunidad pasó sin poder aplicarse. |
| Rechazar | La tesis, el riesgo o el contrato no son aceptables. |
| Cerrar | La alerta ya no necesita seguimiento. |

En **IBKR aplicada**, escribe una nota, el precio real de fill y la cantidad. Un seguimiento `Paper` nunca debe registrarse como una ejecución real.

## 9. Bloque Posiciones

Muestra primero las posiciones que requieren atención. Cada tarjeta enseña inicialmente sólo la acción recomendada, el motivo y el contrato. **Ver detalles y registrar gestión** abre datos, tesis y acciones secundarias.

Cada posición incluye además **Posibilidades de gestión**. No es una lista genérica de botones: cambia según el instrumento. Las acciones largas comparan mantener, covered call parcial o total, protective put, collar, reducciones parciales y salida; las puts vendidas y covered calls comparan mantener, recomprar, rolar, asignación y defensa; las opciones largas y cualquier riesgo descubierto reciben rutas específicas. Cada posibilidad indica si está **lista para revisión**, si **falta cadena**, **falta precio**, **faltan datos** o conviene **esperar liquidez**.

Para acciones largas, la tarjeta presenta una sola **Recomendación del motor** y debajo cuatro perspectivas compactas: **Mayor protección**, **Mejor balance**, **Prima y recuperación** y **Mayor subida**. Al abrir **Ver comparación numérica y supuestos** puedes comparar mantener, reducir 25%, covered call parcial y collar en cinco escenarios: caída fuerte (estrés de al menos -20%, o tres ATR si resulta más severo), soporte, lateralidad, resistencia y subida fuerte. Los importes son estimaciones desde el precio actual, antes de comisiones e impuestos; las ponderaciones ayudan a revisar y no son probabilidades ni garantías.

### Cómo leer un collar recomendado

Un **collar** siempre tiene dos patas sobre la misma cantidad de acciones y, para esta comparación, el mismo vencimiento:

| Pata | Qué aparece en la consola | Qué significa |
|---|---|---|
| Call vendida | `C`, strike, vencimiento y prima calculada con bid | Cobra prima, pero limita la subida de las acciones cubiertas por encima de ese strike. |
| Put comprada | `P`, strike, vencimiento y costo calculado con ask | Protege las acciones cubiertas por debajo de ese strike hasta el vencimiento. |
| Cantidad | Número de contratos y porcentaje de cobertura | Cada contrato corresponde a 100 acciones. |
| Acciones sin collar | Acciones totales menos contratos × 100 | Conservan todo su riesgo y toda su subida; no tienen ni call ni put. |

**Parcial** significa que sólo una parte de las acciones lleva ambas patas. **Total** significaría poner una call y una put por cada lote de 100 acciones. La consola actual compara cuantitativamente **collares parciales** cercanos al objetivo de 25%. La posibilidad denominada **Covered call sobre todos los lotes disponibles** no es un collar total: vende calls sobre todos los lotes, pero no compra puts protectoras.

Ejemplo real capturado el **20 de julio de 2026** para explicar la lectura —no debe reutilizarse como recomendación futura—:

- Posición: 1,000 acciones de NFLX.
- Collar parcial: 3 contratos, equivalente a 300 acciones o 30% de la posición.
- Pata de ingreso: vender 3 calls NFLX strike 65, vencimiento 28 de agosto de 2026; bid observado 4.60.
- Pata de protección: comprar 3 puts NFLX strike 62, mismo vencimiento; ask observado 1.01.
- Crédito neto indicativo: 4.60 − 1.01 = 3.59 por acción cubierta, aproximadamente $1,077 para 3 contratos antes de comisiones, deslizamiento e impuestos.
- Resultado estructural: 300 acciones quedan protegidas por debajo de 62 y limitadas por encima de 65; las otras 700 permanecen sin collar y conservan toda su exposición.

Los strikes, vencimiento, bid, ask, cantidad y ganador cambian con el precio, la cadena, la volatilidad, el soporte y la concentración. Para operar la lectura correcta usa siempre la línea **Contrato preferido visible** y **Put protectora** de la tarjeta actual, no los números históricos de este ejemplo.

La tarjeta destaca primero una sola **Recomendación del motor**, que también puede ser **Mantener y monitorear**. Explica por qué la priorizó, su confianza y el contrato preferido cuando aplica. Las demás rutas quedan dentro de **Ver otras posibilidades** para no confundir la acción principal con una lista de opciones equivalentes.

Cuando termines de evaluar una posición que requiere decisión humana, presiona **Marcar revisión completada**. La consola guarda una huella de la posición, el estado y los contratos recomendados, y la elimina de **Pendientes priorizados**. Volverá a aparecer si cambia la posición, la acción principal, la cantidad, el strike, el vencimiento o alguna pata de la estructura. Una posición marcada **Actualizar datos** no puede ocultarse sólo como revisada: usa **Ir a actualizar datos** y ejecuta **Refresh posiciones IBKR**; desaparecerá cuando el motor reciba la información necesaria.

La apertura diaria incorpora automáticamente todos los símbolos encontrados en posiciones abiertas al escaneo de opciones. La última cadena no vacía de cada símbolo se conserva para gestión, evitando que un refresco posterior de otros tickers borre sus alternativas. “Lista para revisión” nunca significa orden autorizada: toda ejecución continúa siendo manual en el broker.

Para una acción ya abierta, el escaneo incluye calls **ITM, ATM y OTM**. El tamaño parcial se calcula con lotes reales de 100 acciones: por ejemplo, sobre 1,000 acciones, un objetivo cercano a 25% compara 2 contratos (20%) y 3 contratos (30%). La recomendación usa el ganador del balance; romper soporte o superar 60% del valor neto de la cuenta da prioridad a reducir, mientras que sobreventa y cobertura existente activan sus propios límites de seguridad.

La misma apertura obtiene velas históricas de cada subyacente abierto aunque ya tenga precio vivo. Con ellas calcula tendencia, SMA 10/20/50, RSI 14, ATR 14 y soportes/resistencias de 20 y 50 sesiones. La prima de una opción nunca se usa como precio del activo. Si falta evidencia suficiente, la recomendación debe ser no hacer cambios hasta actualizar los datos.

El motor tampoco propone reducir acciones si eso dejaría una call descubierta, ni prioriza vender una covered call nueva sobre un activo sobrevendido sin confirmación adicional. En posiciones cubiertas, la pata de acciones remite la gestión a la operación completa.

Las posiciones abiertas de futuros (`FUT`), por ejemplo MNQ, también se importan desde la Torre de Control aunque no estén presentes en el snapshot antiguo de posiciones. Aparecen como revisión explícita de riesgo direccional: dirección, cantidad, vencimiento y valor de mercado. La consola exige revisar el plan de riesgo; no inventa stop ni objetivo cuando esos datos no existen y nunca cierra la posición automáticamente.

En **Capacidad y administración operativa → Contexto técnico complementario** puedes seleccionar cualquier activo abierto y pegar el mismo JSON o texto usado para RSP. Spot, soportes, resistencias, expected move y gamma complementan la lectura automática; no sustituyen las velas ni convierten la recomendación en una orden.

- estrategia, tipo de instrumento, cantidad, strike y DTE;
- captura de prima, PnL y peso en cartera;
- tendencia, precio, soporte, resistencia y gamma disponible;
- acción de gestión sugerida y estado de salida;
- advertencias, bloqueos y tesis registrada.

### Estados de gestión

- **NO_ACTION_RECOMMENDED / MONITOR:** no hay acción inmediata; vigilar.
- **REFRESH / WAIT:** los datos deben actualizarse antes de decidir.
- **REVIEW:** existe un punto que requiere revisión humana.
- **RISK / DEFENSIVE / ASSIGNMENT:** revisar con prioridad el riesgo, defensa o asignación.

### Acciones disponibles

- **Editar tesis y datos de entrada:** guarda razón de entrada, invalidación, objetivo, crédito, fecha y plan de roll/asignación.
- **Mantener sin cambios:** registra que se revisó y no se actuó.
- **Revisé cierre / Revisé roll / Asignación / Riesgo:** deja evidencia de la revisión realizada; no ejecuta nada.
- **Datos frescos:** registra que se actualizó la información.
- **Refresh posiciones IBKR:** vuelve a leer broker, posiciones y opciones. Úsalo si aparece información vieja o incompleta.

## 10. Bloque principal Coberturas RSP

RSP forma parte del flujo principal, inmediatamente después de Posiciones. El panel presenta primero la decisión, frescura, capacidad y candidatos. El editor para pegar la lectura está dentro de **Actualizar lectura de mercado RSP**.

La estrategia RSP tiene una asignación de cuenta independiente: **RSP → retiro**. La cuenta activa general puede seguir siendo otra. Tanto **Apertura diaria** como **Actualizar sólo RSP** consultan posiciones, capacidad, cadena y margen de RSP usando `retiro`, sin cambiar la selección general del operador.

La gestión y la bitácora se reconcilian automáticamente con IBKR. Cuando aparece una posición RSP en `retiro`, la consola identifica acciones, put/call, cantidad, strike y vencimiento; crea el registro abierto y cambia el motor de búsqueda de entrada a gestión. Un cambio de contrato se registra como rolleo detectado y la desaparición de la posición como cierre detectado. Las notas manuales son opcionales y no son necesarias para que el motor gestione la posición.

- **Lectura manual:** spot, soportes, resistencias, expected move, gamma, call wall y put wall.
- **Cadena IBKR:** contratos reales y actuales, bid/ask, delta, vencimiento y DTE.

Al presionar **Guardar lectura RSP**, el JSON queda almacenado y se interpreta inmediatamente. **Apertura diaria** comprueba que esa lectura sea fresca y ejecuta un refresh exclusivo de RSP para vencimientos de 7–14 DTE. El resultado muestra por separado `contexto`, `cadena` y `candidatos`.

Si el contexto aparece fresco pero la cadena queda pendiente, el JSON sí fue guardado; lo que falta es la respuesta completa de IBKR. El motor excluye de candidatos vigentes cualquier contrato que no provenga de la cadena RSP actual o quede fuera de 7–14 DTE. Los contratos históricos sólo pueden aparecer en diagnóstico técnico.

La cadena semanal RSP se conserva en un archivo independiente: un refresco general ya no puede reemplazarla. La apertura también actualiza la capacidad de la cuenta antes de comparar estrategias.

En capital, la consola diferencia:

- **Exposición nominal:** valor total de las 100 acciones o del strike por 100; puede rondar los $21,000 y no representa necesariamente el margen exigido.
- **Margen confirmado por IBKR:** tiene prioridad cuando el cálculo `what-if` devuelve un resultado completo.
- **Margen estimado configurado:** si IBKR no devuelve margen, se usa una referencia operativa de $7,000 (`STOCK_ULTIMUS_RSP_MARGIN_ESTIMATE`). La consola la identifica como estimación y nunca como confirmación del broker.

Para covered calls, los strikes **ITM, ATM y OTM están permitidos**. La cadena ampliada compara hasta 12 contratos y presenta tres lecturas: **Ingreso y defensa**, **Retorno total flexible** y **Conservar upside**. El perfil operativo predeterminado es **Retorno total flexible**; pondera prima, protección bajista, ganancia total si hay asignación, probabilidad aproximada, spread y participación alcista. La ganancia máxima de una call ITM descuenta correctamente la diferencia entre el precio pagado por las acciones y un strike inferior. El ganador de cada perfil es comparativo: si falta prima utilizable o el spread es demasiado amplio, la consola indica **esperar mejor liquidez** y no lo presenta como listo para revisión operativa.

Una posición RSP abierta no detiene la búsqueda de oportunidades. La consola trabaja en dos carriles simultáneos: **Gestión actual**, para vigilar cierres, rollos y asignación de los contratos existentes; y **Nueva posición**, para comparar otro sell put contra otro bloque de 100 acciones + covered call. Cada entrada nueva se limita a un contrato. El máximo predeterminado es de tres ciclos RSP simultáneos (`STOCK_ULTIMUS_RSP_MAX_CONCURRENT_CYCLES`) y siempre queda subordinado a los fondos disponibles, poder de compra, margen estimado o confirmado por IBKR, calidad de la cadena y revisión humana. Que exista espacio dentro del límite no significa que exista capital suficiente.

## 11. Bloque Riesgo

Es la prioridad principal antes de aumentar exposición. Incluye:

- estado global de riesgo;
- score explicable de `0` a `100`;
- cantidad de alertas críticas, altas y de vigilancia;
- métrica afectada, valor observado, límite y acción recomendada;
- evaluación por cuenta y consolidada.

**Nivel de riesgo** resume severidad y cantidad de brechas. Un valor alto significa más riesgo; no es salud ni rendimiento esperado.

### Niveles

- **CRITICAL:** atención inmediata; no aumentar exposición.
- **HIGH:** riesgo importante que debe revisarse antes de una nueva decisión.
- **WATCH:** condición a vigilar.
- **INFO:** observación sin bloqueo inmediato.

La consola muestra primero las tres alertas principales; las demás están en **Ver alertas adicionales**.

### Acciones de ciclo de vida

- **Confirmar que lo revisé:** reconoce la alerta durante cuatro horas; no elimina el riesgo.
- **Recordar en 60 min:** pospone temporalmente el recordatorio; no resuelve la causa.
- **Reabrir ahora:** devuelve una alerta reconocida o silenciada a atención inmediata.
- **Reevaluar riesgo:** recalcula con los snapshots actuales. No liquida posiciones.

## 12. Cartera avanzada

Se abre sólo para análisis de cartera o multicuenta.

### Control Tower multicuenta

Consolida las cuentas configuradas sin mostrar sus identificadores reales. Enseña NAV, fondos disponibles, buying power, frescura y número de posiciones por alias.

`READY` significa que las cuentas esperadas tienen información utilizable. `WAIT_ACCOUNT_REFRESH` indica que alguna necesita actualización.

### Estrés y escenarios multicuenta

Estima cómo se comportaría la cartera bajo escenarios adversos. Muestra impacto monetario, pérdida sobre NAV, NAV proyectado y cuenta más expuesta. Es una sensibilidad matemática, no un pronóstico.

### Inteligencia avanzada de cartera

Resume:

- cobertura histórica y de griegas;
- volatilidad y pérdida de cola estimada;
- factores dominantes y concentraciones;
- correlaciones;
- dollar delta, theta, vega y gamma agregados.

### Simulador de rebalanceo

Compara alternativas virtuales para reducir concentración, estrés o exposición. **Simular solamente** altera una copia matemática, no la cartera real. La alternativa marcada como “mejor equilibrio” es una comparación del modelo, no una instrucción.

### Validación oficial IBKR what-if

Solicita a IBKR una vista previa de margen y comisión. El modo `what-if` impide crear una orden real. Si TWS pide confirmación, la decisión debe atenderse manualmente; la consola no desactiva protecciones globales.

### Operación y mantenimiento

Muestra automatizaciones locales de riesgo, outbox, digest, acciones humanas y sesiones limpias de observación. Recalcula y archiva; no consulta ni opera el broker al ejecutar el mantenimiento local.

## 13. Resultados y aprendizaje

Esta sección sirve para evaluar si las decisiones y alertas realmente funcionan con evidencia acumulada.

### Historial de decisiones y resultados

Relaciona decisiones con resultados, PnL y estrategia. **Actualizar seguimiento ahora** evalúa checkpoints y sincroniza diarios; no toca IBKR.

La consola exige **30 resultados cerrados y completos por grupo relevante de estrategia/régimen** antes de considerar una revisión profesional de parámetros. Hasta entonces, “acumulando evidencia” es el estado correcto.

### Efectividad del alertamiento

Mide alertas lógicas, duplicados, seguimiento, precisión, falsas alarmas, oportunidades perdidas y bloqueos correctos. Las métricas sólo son válidas cuando existe un resultado cerrado vinculado. `Sin muestra` no es 0%; significa que todavía no hay evidencia suficiente.

### Reporte ejecutivo

Resume diariamente y semanalmente cartera, riesgo, alertas, resultados y pendientes. Los reportes se archivan localmente; no envían mensajes ni cambian reglas.

### Learning y Performance

Permite revisar desempeño y calidad por estrategia, fuente y régimen. El sistema no cambia parámetros por sí solo.

## 14. Herramientas y administración

Es una zona de uso ocasional. Incluye:

- **Estado Ejecutivo y Revisión Manual V31:** vista detallada de estados, bloqueos y contratos.
- **Pregunta operativa local:** consulta explicaciones del motor desde la consola.
- **Capacidad IBKR:** capital y margen disponibles.
- **Gamma manual:** captura contexto de gamma cuando se requiera.
- **Administración desde esta consola:** acciones técnicas controladas.
- **Contexto activo:** muestra qué cuenta y ámbito están publicados.
- **Prueba de notificaciones:** valida los canales configurados.
- **Mantenimiento preventivo:** revisa datos, procesos, IBKR, históricos, almacenamiento y espacio libre.
- **Diagnóstico técnico y salud de módulos:** semáforos internos, timeline y detalle para investigar fallas.
- **Cuentas y perfiles:** selección y configuración de alias de cuenta.

### Política de notificaciones móviles

Pushover sólo envía condiciones `ENTRY`/`ENTRY_READY`. Ninguna opción de `force` puede convertir WATCH, RISK, validaciones, problemas de IBKR o resúmenes en una alerta móvil. Esos estados se consultan en **Inicio**, **Pendientes**, **Riesgo** y **Alertas y diagnósticos** dentro de la consola. La prueba manual del canal sigue disponible en Administración y sólo se ejecuta cuando el operador la solicita expresamente.

En perfiles de cuenta:

- **Usar cuenta** selecciona y publica el contexto para GPT.
- **Refresh IBKR** trae datos nuevos del broker para esa cuenta.

Son acciones distintas. Seleccionar una cuenta no equivale a refrescar sus datos.

## 15. Diccionario de términos

| Término | Significado sencillo |
|---|---|
| Alias | Nombre lógico de una cuenta; evita mostrar el identificador real. |
| Snapshot | Fotografía de datos usada por el motor en un momento determinado. |
| Contexto GPT | Cuenta y datos que el GPT oficial consulta en producción. |
| Capacidad | Capital, margen y fondos disponibles para evaluar viabilidad. |
| DTE | Días que faltan para el vencimiento. |
| Bid / Ask | Mejor precio comprador y vendedor disponible. |
| Mid | Punto medio entre bid y ask. |
| Spread | Distancia entre bid y ask; cuanto mayor, peor liquidez relativa. |
| Delta | Sensibilidad aproximada de la opción al movimiento del subyacente. |
| Theta | Cambio estimado por el paso de un día. |
| Vega | Sensibilidad a cambios de volatilidad implícita. |
| Gamma | Cambio de delta al moverse el subyacente. |
| IV / IV Rank | Volatilidad implícita y su posición relativa histórica. |
| NAV | Valor neto de liquidación de la cuenta o cartera. |
| Buying power | Capacidad de compra reportada por el broker. |
| CANSLIM | Contexto fundamental/de crecimiento usado como filtro complementario. |
| TTL | Tiempo de vigencia asignado a una alerta. |
| Paper | Seguimiento simulado, sin operación real. |
| What-if | Vista previa oficial de margen/comisión sin crear una orden real. |

## 16. Qué hacer ante problemas comunes

### La consola no abre

1. Vuelve a abrir **Stock Ultimus Console.command**.
2. Espera unos segundos.
3. Si no abre, confirma que estás dentro de tu sesión normal de macOS y vuelve a intentarlo.

### IBKR aparece `NO`

1. Abre o desbloquea TWS/IB Gateway.
2. Confirma que el acceso API siga habilitado.
3. Presiona **Validar IBKR**.
4. Si valida, ejecuta **Refresh posiciones IBKR** o **Apertura diaria** según la necesidad.

### Producción o contexto GPT no están alineados

1. Presiona **Actualizar estado**.
2. Si el problema es contexto, usa **Alinear/Publicar rápido**.
3. Verifica que el alias mostrado sea la cuenta que deseas revisar.

### Aparecen datos viejos

Ejecuta un refresh de IBKR y espera a que termine. No tomes decisiones de contrato, capacidad o riesgo usando un snapshot marcado como viejo.

### No aparecen oportunidades

Puede ser correcto. Revisa si el mercado está cerrado, si faltan eventos reales de TradingView o si las oportunidades quedaron ocultas como diagnóstico por no superar las puertas de calidad. La ausencia de alerta es preferible a forzar una señal débil.

Para futuros, **Apertura diaria** también ejecuta la reconciliación de señales. Si TradingView recibió una señal pero la consola no pudo procesarla antes de un reinicio, la recupera desde el almacenamiento permanente, evita duplicarla y la incorpora a **Futuros Intradía** si todavía está vigente. Si esta comprobación falla, la apertura queda en `ACTION_REQUIRED` y no debe asumirse que “no hubo señales”.

Los eventos productivos de MES/MNQ enviados con `is_validation:false` se consideran reales; solamente `is_validation:true` o una fuente expresamente sintética se excluye. El ciclo postcierre evalúa además `/intraday_futures/evaluate_pending`, de modo que los resultados de futuros no quedan fuera del aprendizaje diario cuando ya existe un precio posterior utilizable.

### Una acción muestra error

Lee primero el resumen amigable de la última acción. Abre el detalle técnico únicamente si necesitas diagnóstico. No repitas acciones de publicación o refresh sin entender si la anterior terminó.

## 17. Reglas de oro

1. **Riesgo antes que oportunidad.**
2. **Dato viejo equivale a decisión pendiente.**
3. **ENTRY_READY todavía exige revisión humana.**
4. **WAIT y NO_DATA nunca son permisos para operar.**
5. **Paper no es una operación real.**
6. **Registrar “IBKR aplicada” no ejecuta nada; documenta lo que ya hiciste manualmente.**
7. **No lances dos refresh al mismo tiempo.**
8. **No cambies parámetros por resultados incompletos.**
9. **La consola recomienda y registra; TWS ejecuta bajo decisión humana.**

## 18. La versión más corta posible

Si sólo recuerdas una secuencia, usa ésta:

```text
Abrir TWS → Abrir consola → Ejecutar apertura diaria → Esperar DONE
→ Leer Inicio y Pendientes → Atender Riesgo
→ Administrar Posiciones → Revisar RSP → Registrar lo realizado
→ Ejecutar manualmente en TWS sólo si tu revisión lo aprueba
```
