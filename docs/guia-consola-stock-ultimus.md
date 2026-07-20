# Guía de uso de Stock Ultimus Console

Esta guía explica cómo quedó funcionando la consola, qué significa cada bloque y cómo operarla de forma segura. Está escrita para el operador; no hace falta conocer el código del proyecto.

**Documento oficial del proyecto:** la consola muestra directamente este archivo mediante el botón **Guía**. Toda modificación que agregue, quite o cambie una sección, estado, botón o flujo operativo debe actualizar también esta guía. Las validaciones automáticas comprueban que las secciones principales de navegación continúen documentadas.

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
  Hoy → Alertas → Posiciones → Riesgo → Cartera avanzada
                    → Resultados → Herramientas
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
3. Mira primero el semáforo superior.
4. Pega y guarda primero la lectura diaria de Coberturas RSP cuando tengas un JSON nuevo de gamma/niveles.
5. Presiona **Apertura diaria**. El ciclo valida el contexto RSP guardado y consulta una cadena RSP independiente de 7–14 DTE.
6. Espera a que el proceso muestre `DONE`. No vuelvas a presionar el botón mientras esté trabajando.
7. Lee **Modo Hoy** y el **Siguiente paso recomendado**.
8. Atiende en este orden: **Riesgo**, **Alertas**, **Posiciones**.

La apertura puede tardar varios minutos porque el refresh principal y el refresh específico de RSP son procesos separados. Mientras la consola muestre que está trabajando, no inicies una segunda apertura.

Durante la apertura, el puente reúne primero precios, posiciones y contratos en el entorno local. La publicación se realiza después como un snapshot consolidado; así una respuesta lenta de producción no detiene cada contrato individual.

### Durante la sesión

1. Usa **Actualizar estado** para releer producción y buscar alertas nuevas.
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

### Los cinco indicadores

| Indicador | Qué significa | Si aparece `NO` o pendiente |
|---|---|---|
| Producción | La consola puede leer el estado protegido del motor publicado. | Usa **Actualizar estado**; si persiste, revisa conexión o acceso. |
| IBKR | Hay evidencia de conexión local con TWS/IB Gateway. | Abre/desbloquea TWS y usa **Validar IBKR**. |
| Contexto GPT | La cuenta y el contexto que consulta el GPT están alineados. | Usa **Alinear/Publicar rápido**. |
| Datos snapshot | Existe un paquete local de datos para evaluar. | Ejecuta **Apertura diaria** o un refresh de IBKR. |
| Capacidad | Hay datos de capital, margen y disponibilidad de la cuenta. | Actualiza IBKR antes de evaluar tamaño o viabilidad. |

### Botones rápidos

| Botón | Para qué sirve | Qué no hace |
|---|---|---|
| Actualizar estado | Relee producción, GPT y alertas. | No cambia cuenta y no consulta profundamente IBKR. |
| Apertura diaria | Ejecuta CANSLIM, refresh principal de IBKR, refresh RSP 7–14 DTE, publicación, validaciones y reporte. | No autoriza órdenes. |
| Validar IBKR | Prueba rápidamente TWS/API, cuenta y capacidad. | No hace un escaneo profundo de opciones. |
| Alinear/Publicar rápido | Corrige la cuenta y el contexto que ve GPT. | No sustituye un refresh completo de opciones. |

Cuando aparezca **La consola está trabajando**, espera. Lanzar varios refresh simultáneos sólo duplica carga y dificulta interpretar qué resultado es el más reciente.

## 6. Navegación principal

La barra fija permite saltar directamente a:

1. **Hoy**
2. **Alertas**
3. **Posiciones**
4. **Riesgo**
5. **Cartera**
6. **Resultados**
7. **Herramientas**

Los primeros cuatro bloques son de uso diario. Cartera, Resultados y Herramientas permanecen cerrados para mantener la pantalla simple y se abren sólo cuando hacen falta.

## 7. Bloque Hoy

**Modo Hoy** resume la situación actual y evita que el operador tenga que interpretar toda la página antes de actuar.

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

Debajo aparecen cuatro lecturas:

- **Estado operador:** estado general y conteo de pendientes.
- **Está esperando:** principal dato, evidencia o acción pendiente.
- **Última alerta viva:** la alerta pendiente de mayor prioridad.
- **Mercado:** sesión abierta/cerrada y nivel de madurez operativa (`edge`).
- **Última apertura:** conserva el resultado del último ciclo aunque después corran notificaciones o mantenimiento; también indica si RSP quedó actualizado.

El `edge` mide madurez y calidad de evidencia del sistema; **no es una probabilidad de ganancia ni una señal de entrada**.

## 8. Bloque Alertas

La consola separa las alertas para reducir ruido:

- **Alertas Operables:** configuraciones con suficiente calidad para revisión humana.
- **Futuros Intradía:** señales rápidas de MNQ/MES recibidas desde TradingView.
- **Diagnóstico oculto:** casos con datos insuficientes, espera, bloqueo o calidad baja.
- **Ya revisadas/en seguimiento/cerradas:** historial operativo reciente.

Que una alerta aparezca como operable significa **“revisar ahora”**, no “ejecutar ahora”.

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

Muestra las posiciones activas detectadas y ayuda a administrarlas. Para cada posición presenta:

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
- **No tocar:** registra que se revisó y no se actuó.
- **Revisé cierre / Revisé roll / Asignación / Riesgo:** deja evidencia de la revisión realizada; no ejecuta nada.
- **Datos frescos:** registra que se actualizó la información.
- **Refresh posiciones IBKR:** vuelve a leer broker, posiciones y opciones. Úsalo si aparece información vieja o incompleta.

## 10. Bloque Riesgo

Es la prioridad principal antes de aumentar exposición. Incluye:

- estado global de riesgo;
- score explicable de `0` a `100`;
- cantidad de alertas críticas, altas y de vigilancia;
- métrica afectada, valor observado, límite y acción recomendada;
- evaluación por cuenta y consolidada.

El score resume severidad y cantidad de brechas. No es rendimiento esperado.

### Niveles

- **CRITICAL:** atención inmediata; no aumentar exposición.
- **HIGH:** riesgo importante que debe revisarse antes de una nueva decisión.
- **WATCH:** condición a vigilar.
- **INFO:** observación sin bloqueo inmediato.

La consola muestra primero las tres alertas principales; las demás están en **Ver alertas adicionales**.

### Acciones de ciclo de vida

- **Confirmar 4 h:** reconoce la alerta durante cuatro horas; no elimina el riesgo.
- **Silenciar 60 min:** reduce temporalmente la repetición; no resuelve la causa.
- **Reabrir ahora:** devuelve una alerta reconocida o silenciada a atención inmediata.
- **Reevaluar riesgo:** recalcula con los snapshots actuales. No liquida posiciones.

## 11. Cartera avanzada

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

### Coberturas RSP dentro de la apertura

La lectura manual que pegas en **Coberturas RSP** y la cadena consultada a IBKR son dos piezas diferentes:

- **Lectura manual:** spot, soportes, resistencias, expected move, gamma, call wall y put wall.
- **Cadena IBKR:** contratos reales y actuales, bid/ask, delta, vencimiento y DTE.

Al presionar **Guardar lectura RSP**, el JSON queda almacenado y se interpreta inmediatamente. A partir de ahora, **Apertura diaria** también comprueba que esa lectura sea fresca y ejecuta un refresh exclusivo de RSP para vencimientos de 7–14 DTE. El resultado de apertura muestra por separado `contexto`, `cadena` y `candidatos`.

Si el contexto aparece fresco pero la cadena queda pendiente, el JSON sí fue guardado; lo que falta es la respuesta completa de IBKR. Un contrato viejo, fuera de 7–14 DTE o sin bid/ask no debe usarse como candidato actualizado.

## 12. Resultados y aprendizaje

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

## 13. Herramientas y administración

Es una zona de uso ocasional. Incluye:

- **Coberturas RSP:** análisis de coberturas y niveles; no ejecución.
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

En perfiles de cuenta:

- **Usar cuenta** selecciona y publica el contexto para GPT.
- **Refresh IBKR** trae datos nuevos del broker para esa cuenta.

Son acciones distintas. Seleccionar una cuenta no equivale a refrescar sus datos.

## 14. Diccionario de términos

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

## 15. Qué hacer ante problemas comunes

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

### Una acción muestra error

Lee primero el resumen amigable de la última acción. Abre el detalle técnico únicamente si necesitas diagnóstico. No repitas acciones de publicación o refresh sin entender si la anterior terminó.

## 16. Reglas de oro

1. **Riesgo antes que oportunidad.**
2. **Dato viejo equivale a decisión pendiente.**
3. **ENTRY_READY todavía exige revisión humana.**
4. **WAIT y NO_DATA nunca son permisos para operar.**
5. **Paper no es una operación real.**
6. **Registrar “IBKR aplicada” no ejecuta nada; documenta lo que ya hiciste manualmente.**
7. **No lances dos refresh al mismo tiempo.**
8. **No cambies parámetros por resultados incompletos.**
9. **La consola recomienda y registra; TWS ejecuta bajo decisión humana.**

## 17. La versión más corta posible

Si sólo recuerdas una secuencia, usa ésta:

```text
Abrir TWS → Abrir consola → Apertura diaria → Esperar DONE
→ Leer Modo Hoy → Atender Riesgo → Revisar Alertas
→ Administrar Posiciones → Registrar lo realizado
→ Ejecutar manualmente en TWS sólo si tu revisión lo aprueba
```
