# Stock Ultimus Project Dashboard

Ultima actualizacion: 2026-07-11

Este tablero resume como vamos, que esta validado y que falta para considerar
Stock Ultimus operativo al 100% para uso personal controlado. El sistema sigue
siendo un asistente de decision: no autoriza ni ejecuta ordenes.

Vista visual amigable: `docs/project-dashboard.html`.

Vista ejecutiva tipo Kanban: `docs/project-command-center.html`.

Rutas protegidas en produccion:

- `/v32_project_dashboard`
- `/v32_project_command_center`
- `/v32_project_command_center_static`

## Estado Ejecutivo

Estado actual separado por frente:

- Operativo personal V31: sano a nivel plataforma, auth, GPT Action, manual
  review y guardrails. Hoy 2026-07-05 el radar no tiene snapshot maestro activo
  y queda en `NO_DATA` / `WAIT_PIPELINE`, esperado para un domingo o antes de
  refrescar IBKR/TWS + TradingView. No hay oportunidades accionables.
- Terceros/comercial: no liberado. Sigue bloqueado hasta completar
  aislamiento por cliente/cuenta, tokens separados, durable audit logging,
  disclosures, legal/compliance review, onboarding paper/sim y proceso de
  soporte/incidentes.

Resumen:

- Prioridad activa: mantener operativo personal listo y separar claramente
  terceros/comercial.
- El Command Center productivo existe en `/v31_command_center` y JSON en
  `/v31_command_center.json`.
- El GPT oficial debe usar la accion `getDailyNow` con
  `X-Stock-Ultimus-Read-Token`.
- Hay preflight `scripts/stock_ultimus_operational_100_check.py` para validar
  las compuertas operativas.
- Hay checklist de apertura `scripts/daily_open_checklist.py` para validar TWS,
  tokens, runtime, produccion y V32 antes de preguntarle al GPT.
- Hay notificador V32 `scripts/v32_operator_notify.py --macos-notify` que avisa
  solo cuando hay `ACTION`, `RISK` o manual review listo; suprime `WAIT_MARKET`.
- El Command Center productivo `/v32_project_command_center` ahora es una vista
  viva basada en `/v32_operator_daily_summary` y
  `/v32_operator_tracking_status`; la version estatica queda en
  `/v32_project_command_center_static`.
- El notificador tambien soporta `--pushover`, `--webhook-url` y
  `--email-summary` para celular, integraciones externas y correo.
- Pushover ya tiene automatizacion local via launchd:
  `scripts/install_v32_pushover_launchd.py --install`; monitor cada 5 minutos,
  post-cierre deduplicado y preflight diario, todo sin secretos en plist.
- Render declara `PUSHOVER_USER_KEY` y `PUSHOVER_API_TOKEN`; con esos secretos
  cargados, `/v32_operator_pushover_notify/preview` previsualiza y
  `POST /v32_operator_pushover_notify` envia push protegido por read-auth.
- GitHub Actions agrega scheduler cloud `.github/workflows/v32-cloud-pushover.yml`;
  el backend deduplica alertas `ACTION`/`RISK` para no repetir pushes.
- GitHub Actions agrega nudges proactivos `.github/workflows/v32-operator-nudges.yml`;
  llama `POST /v32_operator_nudge` durante el dia y el backend decide por
  horario NY (`premarket`, `open_check`, `midday`, `power_hour`, `post_close`),
  dedupe y read-auth. Los nudges preguntan al operador que revisar, no ejecutan.
- GitHub Actions agrega watch inmediato `.github/workflows/v32-actionable-signal-watch.yml`;
  llama `POST /v32_actionable_signal_watch` cada 5 minutos durante mercado
  amplio y avisa por Pushover solo si aparece una nueva senal `ACTION`,
  `ENTRY_READY` o `manual_review_ready=true` para revision manual en IBKR.
- Preflight de nudges: `GET /v32_operator_nudge_preflight`; valida Pushover,
  read-auth, slots, prompts del GPT, checklist de primer dia habil y playbook
  de respuestas (`MARK_WATCHLIST`, `REJECT_SETUP`, `CLOSE_ALERT`, etc.).
- El GPT puede usar `/gpt_v32_operator_daily_cycle` como flujo unico: estado,
  Pushover, nudges, tracking y backtesting/post-cierre.
- Hay ciclo diario `scripts/run_operating_day.py --allow-partial`.
- Hay capa V32 Operational Edge: `/v32_operational_edge` y
  `/v32_operational_edge_dashboard`; consolida los 7 frentes de mejora para
  llevar el sistema al siguiente nivel sin autorizar ordenes.
- La consola local `python3 scripts/ibkr_account_profile.py serve` es el cockpit
  operativo principal: muestra foco de salud, procesos RUNNING/DONE, capacidad
  IBKR, contexto GPT, alertas V32 y marcas visibles de revision.
- Manual review tiene inbox, historial, learning y performance dashboards.
- Outcome real queda bloqueado hasta post-cierre con snapshot fresco y bandera
  explicita `--real-outcomes-after-close`.
- Regla de seguridad: `execution_authorized=false` y `not_order_instruction=true`
  deben conservarse siempre.

Estado de evidencia local al 2026-07-05: `foundation_health` esta en `WARN`,
con `decision_count=140`, `entry_ready_count=69`, `option_row_count=106`,
source attribution coverage de 92.86%, `closed_outcomes=1` y
`complete_closed_outcomes=0`. Esto confirma que ya hay base historica/local,
pero todavia falta completar ledger TradingView, cobertura completa de opciones
y outcomes cerrados suficientes antes de promover cambios de parametros.

## Estado Operativo Personal

Los 5 pendientes reales del uso personal siguen cerrados:

| # | Pendiente | Evidencia | Estado |
| --- | --- | --- | --- |
| 1 | Validar GPT Action en Builder | GPT Builder muestra `GPT Updated` el 2026-06-26; Action sigue con API Key custom y `X-Stock-Ultimus-Read-Token`. | Cerrado |
| 2 | Alimentar opciones ejecutables frescas | Cerrado el 2026-06-26 con `rows_found=26`; hoy requiere refresh porque no hay snapshot maestro. | Cerrado historico / refresh hoy |
| 3 | Confirmar TradingView real | Cerrado el 2026-06-26 con `technical_count=10`; hoy requiere refresh porque el radar esta sin snapshot. | Cerrado historico / refresh hoy |
| 4 | Usar manual review como compuerta humana | `check_manual_review_console.py` valida inbox/rutas/cookie auth/email link/no-order; learning evalua 6 de 11 reviews. | Cerrado |
| 5 | Evaluar outcomes/manual reviews | Operating day ejecuto outcome evaluation: pending outcomes evaluados y manual reviews evaluadas; no-order guardrails intactos. | Cerrado |

Estado actual de datos al 2026-07-05: `monitor_gpt_action_health.py` responde
OK, endpoints protegidos responden 200 con token y 401 sin token, pero
`daily_now_status=NO_DATA`, `main_blocker=MASTER_SNAPSHOT_MISSING`,
`option_rows_found=0` y `technical_count=0`. La siguiente accion operativa es
refrescar snapshot durante una ventana util de mercado/opciones.

## Estado Terceros / Comercial

Terceros no esta listo para venderse u operarse fuera del uso personal. El
paquete existe como guia y arquitectura, pero faltan gates obligatorios:

| Gate terceros | Estado actual | Evidencia | Bloqueo |
| --- | --- | --- | --- |
| Legal/compliance review | Bloqueado | `docs/third-party-installation-guide.md` y `docs/customer-package.md` lo exigen. | Falta revision formal antes de prometer asesoria/herramienta comercial. |
| Customer/account isolation | Bloqueado | Hay campos/patrones de `tenant_id`, pero no liberacion multi-cliente. | Falta aislar datos, snapshots, runtime y cuentas por cliente. |
| Tokens separados por cliente | Bloqueado | READ/INGEST funcionan para uso personal. | Falta rotacion y provisionamiento por cliente/cuenta. |
| Durable audit logging | Parcial | Existe contrato/flujo durable en repo, pero no queda validado como requisito comercial completo. | Falta auditoria durable obligatoria por tenant. |
| Risk profile por cliente | Parcial | Presets documentados: conservative/balanced/aggressive/paper. | Falta change log y aprobacion por cliente. |
| Disclosures escritos | Bloqueado | Docs exigen disclosure de decision support/no ordenes/no advice. | Falta paquete legal visible para cliente. |
| Paper/simulation onboarding | Bloqueado | Recomendado en guia. | Falta flujo de onboarding antes de uso real. |
| Soporte/incidentes | Bloqueado | Guia pide soporte para stale data, broker outages y token rotation. | Falta runbook comercial y SLA/proceso. |

Conclusion: operativo personal puede seguir avanzando; terceros/comercial queda
en etapa de preparacion, no de venta.

## Ruta Al 100%

Definicion de 100% en esta rama: el motor operativo V31 queda usable para radar
diario personal cuando el preflight completo contra produccion pase, IBKR/TWS
alimente datos frescos, TradingView entregue contexto real cuando aplique, manual
review se use como compuerta humana y outcomes se evalúen despues del cierre.

| Gate para 100% | Estado actual | Evidencia requerida | Bloqueo |
| --- | --- | --- | --- |
| 1. Preflight operacional completo | OK con warnings | `scripts/stock_ultimus_operational_100_check.py --no-write` devuelve `PASS_WITH_WARNINGS`: 6 gates, 0 fallas, 2 warnings. | Warnings: `foundation_health` y outcome real post-cierre no ejecutado. |
| 2. GPT Action Builder | OK | GPT Builder actualizado y `monitor_gpt_action_health.py` confirma endpoints protegidos. | Mantener secreto vigente. |
| 3. IBKR/TWS real fresco | Listo, requiere refresh | El 2026-06-26 el bridge publico snapshot fresco con 26 filas; hoy no hay snapshot maestro. | Reconsultar durante ventana util. |
| 4. TradingView real | Listo, requiere refresh | El contrato tecnico funciona; hoy `technical_count=0` porque no hay snapshot maestro y el ledger local espera payload. | Confirmar alertas al refrescar pipeline y replay/ingest al ledger. |
| 5. Manual review funcionando | OK | Inbox, historial, learning y performance dashboard abren con read-auth; acciones conservan no-order guardrails. | Usarlo cuando haya `ENTRY_READY` o setups revisables. |
| 6. Outcomes / learning | OK tecnico, muestra insuficiente | Operating day evalua outcomes/manual reviews; `closed_outcomes=1`, `complete_closed_outcomes=0`. | Backfill/re-journal y acumular minimo 30 outcomes completos por estrategia activa. |
| 7. Produccion protegida | OK | `READ_ACCESS_TOKEN`, ingest, read-auth y endpoints sensibles verificados en Render. | Mantener tokens en Keychain deduplicados. |
| 8. Terceros/comercial readiness | Bloqueado | Guia de instalacion y customer package existen. | Faltan legal/compliance, aislamiento, tokens por cliente, audit durable, disclosures, paper onboarding y soporte. |

Lectura rapida: produccion, auth, GPT, manual review y guardrails estan
alineados. El bloqueo operativo actual es de pipeline/datos frescos
(`MASTER_SNAPSHOT_MISSING`); el bloqueo comercial es de gobernanza y
aislamiento.

## Semaforo

| Area | Estado | Evidencia | Siguiente accion |
| --- | --- | --- | --- |
| Operacion V31 | OK con pipeline pendiente | `operational_100_v1`, daily radar y runbook existen; preflight real pasa. | Refrescar IBKR/TWS + TradingView en ventana util; hoy `MASTER_SNAPSHOT_MISSING`. |
| Manual Review | Validado | `check_manual_review_console.py` valida rutas, cookie auth, email link y no-order guardrails. | Abrir inbox productivo cuando haya setups revisables. |
| GPT/backend Action | OK | GPT Builder actualizado; health autorizado 200, no-order guardrails OK y no autorizado 401. | Mantener secreto vigente. |
| IBKR Bridge | Listo, requiere refresh | El 2026-06-26 publico snapshot fresco con 26 filas y termino `PASS`; hoy no hay snapshot maestro activo. | Reconsultar en ventana operativa. |
| TradingView | Listo, requiere refresh | Contrato tecnico integrado; el 2026-06-26 reporto `technical_count=10`; hoy `technical_count=0` por snapshot faltante. | Mantener alertas reales hacia `/technical_snapshot`. |
| Outcomes/Learning | OK | Operating day evaluo outcomes/manual reviews; dry-run tambien pasa. | Seguir post-cierre con snapshot fresco. |
| Operational Edge | Nuevo | Integra confirmacion real, calibracion de score, ranking institucional, optimizador de contratos, CANSLIM dinamico, panel y post-mortem. | Acumular outcomes completos y confirmar eventos reales de mercado. |
| Foundation/Evidencia | WARN | 140 decisiones, 69 `ENTRY_READY` locales, 106 option rows, 92.86% source attribution coverage. | Completar fuentes, ledger TradingView, datos de opciones y outcomes cerrados. |
| Seguridad | Alineado localmente | Preflight no imprime secretos, no toca IBKR en skip-cloud, no autoriza ejecucion. | Verificar read-auth y secrets en Render. |
| Terceros / Comercial | Bloqueado por diseño | Docs exigen aislamiento/compliance antes de terceros. | No vender/operar para terceros hasta cerrar gates comerciales. |

## Validacion Mas Reciente

Fecha: 2026-07-05

Comandos ejecutados:

```bash
python3 scripts/stock_ultimus_operational_100_check.py --skip-cloud --no-write
python3 scripts/stock_ultimus_operational_100_check.py --no-write
python3 scripts/monitor_gpt_action_health.py --base-url https://trading-engine-p097.onrender.com --timeout 45
python3 scripts/check_manual_review_console.py
python3 -m unittest discover -s tests -p 'test_p0_operational_guards.py'
python3 tests/test_v31_operational_check.py
python3 tests/test_v31_daily_operational_audit.py
PYTHONPATH=. python3 tests/test_v31_market_open_runner.py
```

Resultado:

- `operational_100_v1`: `PASS_WITH_WARNINGS` contra produccion.
- Commit `f56ada7` subido por SSH y desplegado live en Render.
- `/health`: `read_auth_required=true`, `read_access_token_configured=true`.
- `READ_ACCESS_TOKEN` local deduplicado en Keychain; lectura normal ya autentica produccion.
- Ingest token local deduplicado en Keychain.
- `verify_production_read_auth.py`: autorizado 200, no autorizado 401, `production_readiness_status=READY`.
- `operational_100_v1` real: `PASS_WITH_WARNINGS`; 6 gates totales, 0 fallas, 2 warnings (`foundation_health` y outcome real post-cierre no ejecutado).
- GPT/backend health: `OK`; autorizado 200, no autorizado 401, no-order guardrails OK.
- Radar diario actual: `NO_DATA`, `MASTER_SNAPSHOT_MISSING`, opciones=0 y tecnicos=0.
- Foundation health local: `WARN`; `decision_count=140`, `entry_ready_count=69`, `closed_outcomes=1`, `complete_closed_outcomes=0`, `option_row_count=106`.
- Source attribution coverage: 92.86%; quedan decisiones con fuente `UNKNOWN` o fuentes candidate/confirmation incompletas.
- TradingView signal ledger: `WAITING_FOR_DATA`; falta replay/ingest de al menos un payload tecnico real.
- Daily operational audit: `PASS_WITH_WARNINGS`, 24/26 checks, warnings por `NO_MASTER_SNAPSHOT` y `SNAPSHOT_MISSING`.
- GPT Builder actualizado: la UI confirma `GPT Updated` el 2026-06-26.
- Outcome/manual-review dry-run: endpoints 200, no-order guardrails intactos, 0 guardados por `--no-write`.
- Strategy performance: `decision_count=48`, `outcome_count=12`, `closed_outcomes=0`; muestra insuficiencia de muestra para todas las estrategias.
- No-order guardrails intactos: `execution_authorized=false`, `not_order_instruction=true`.
- Preflight local previo sin nube reporto 0 fallas; la lectura vigente contra produccion es la de 6 gates, 0 fallas y 2 warnings.
- Manual review console/inbox routes, cookie auth, email link y no-order guardrails validados.
- 20 pruebas operativas P0/operational pasan.
- 8 pruebas de `v31_operational_check` pasan.
- 6 pruebas de daily operational audit pasan.
- 6 pruebas de market-open runner pasan con `PYTHONPATH=.`.
- `pytest` no esta instalado en este entorno; se uso `unittest`/scripts directos.

## Proximas Acciones Operativas

1. En la proxima ventana util, abrir TWS/IBKR y correr el ciclo diario para
   publicar snapshot maestro fresco.
2. Correr `python3 scripts/daily_open_checklist.py --refresh --publish`.
3. Configurar Pushover por env o Keychain y validar con
   `python3 scripts/setup_pushover_channel.py --send-test`.
4. Instalar/validar launchd local con
   `python3 scripts/install_v32_pushover_launchd.py --install` y
   `python3 scripts/install_v32_pushover_launchd.py --status`.
5. Activar `python3 scripts/v32_operator_notify.py --macos-notify --pushover`
   para avisos accionables sin ruido cuando solo haya `WAIT_MARKET`.
6. En ChatGPT Scheduled, crear recordatorios conversacionales con estos prompts:
   `que hago hoy?`, `que hago ahora?`,
   `revisa mi watchlist y dime que requiere decision`,
   `haz revision de cierre intradia`, y
   `haz cierre operativo y backtesting pendiente`.
7. Antes del proximo dia habil, consultar `/v32_operator_nudge_preflight` o
   pedir al GPT: `haz preflight de nudges y dame checklist del lunes`.
8. Confirmar que TradingView vuelva a alimentar `/technical_snapshot`.
9. Reproducir/ingerir al menos un payload TradingView en el ledger tecnico.
10. Backfill/re-journal de outcomes cerrados incompletos: MFE/MAE, regimen,
    fuente y contrato seleccionado.
11. Acumular minimo 30 outcomes cerrados completos por estrategia activa antes
    de tocar parametros.
12. Reconsultar el radar y verificar que salga de `NO_DATA`.
13. Si aparece `ENTRY_READY` o `manual_review_ready>0`, abrir
   `/v31_manual_review_inbox` y registrar decision humana.
14. Despues de cada cierre, seguir evaluando outcomes con snapshot fresco.

## Proximas Acciones Para Terceros

1. Definir si terceros significa SaaS multi-cliente, instalacion privada por
   cliente o uso interno por otra cuenta.
2. Completar legal/compliance review y disclosures escritos.
3. Diseñar aislamiento por tenant/cuenta y tokens separados.
4. Validar durable audit logging por cliente antes de usar outcomes para
   cambios de parametros.
5. Preparar onboarding paper/sim y soporte para stale data, broker outages y
   rotacion de tokens.

## Registro De Avances

| Fecha | Cambio | Evidencia |
| --- | --- | --- |
| 2026-06-25 | Se recrea dashboard para la rama operacional actual. | Se detecta `operational_100_v1`, runbook daily radar, manual review surfaces y Command Center V31. |
| 2026-06-25 | Se valida corte local. | Preflight local `PASS_WITH_WARNINGS`, manual review guard OK y 40 pruebas/checks operativos pasan. |
| 2026-06-26 | Se resuelve auth de produccion. | `f56ada7` desplegado, READ deduplicado en Keychain, `verify_production_read_auth.py` OK. |
| 2026-06-26 | Se cierra ciclo operativo sin ordenes. | `run_operating_day.py --allow-partial` devuelve `PASS`; primer corte quedo `NO_DATA` antes de refrescar option rows/tecnicos. |
| 2026-06-26 | Se actualiza GPT Builder. | Action queda con API Key custom y header correcto; la UI confirma `GPT Updated`. |
| 2026-06-26 | Se cierran los 5 pendientes operativos. | GPT Builder actualizado, option rows=26, technical_count=10, manual review OK, outcomes/manual reviews evaluados; radar queda WAIT_MARKET_WINDOW. |
| 2026-06-28 | Se actualiza estado operativo y terceros. | Produccion/read-auth/manual review OK; radar actual NO_DATA por MASTER_SNAPSHOT_MISSING; terceros sigue bloqueado por gates comerciales. |
| 2026-07-03 | Se refresca dashboard operativo/terceros. | Produccion/read-auth/GPT/manual review OK; preflight PASS_WITH_WARNINGS; pipeline sigue sin snapshot maestro; terceros sigue bloqueado. |
| 2026-07-05 | Se refresca avance real operativo y terceros. | Produccion/read-auth/GPT OK; radar sigue NO_DATA por MASTER_SNAPSHOT_MISSING; foundation_health WARN por muestra/outcomes/fuentes incompletas. |
