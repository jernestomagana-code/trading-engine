# Stock Ultimus Project Dashboard

Ultima actualizacion: 2026-06-23

Este tablero es el punto vivo para saber como vamos. Cada vez que avancemos en
codigo, fixtures, documentacion o validacion, se debe actualizar esta pagina con
el nuevo estado, evidencia y siguiente accion.

Vista visual amigable: `docs/project-dashboard.html`.

Vista ejecutiva tipo Kanban: `docs/project-command-center.html`.
Guia para instalacion/comercializacion controlada:
`docs/third-party-installation-guide.md`.

Nota visual: el Command Center ya refleja que V31 tiene contrato compartido,
V32 tiene adapter Supabase local validado, y que lo pendiente real es reducir
legacy, validar IBKR real, forward test de TradingView y activar Supabase real.

## Estado Ejecutivo

Estado actual: base local validada; el proyecto aun no esta al 100% operativo
porque faltan pruebas reales y despliegue seguro. V30 esta validado, V31/V32
tienen guardrails y contratos compartidos, y TradingView esta listo para
forward test.

Resumen:

- Prioridad activa: V31 Canonical Decision Contract.
- Objetivo: exponer una decision canonica versionada sobre el motor validado,
  con blockers, contrato seleccionado, riesgo, explicacion y no-order guardrails.
- Validacion local del 2026-06-23: pasando para V30, V31, V32 y señales TradingView.
- V32 ya registra decisiones, follow-ups y outcomes con IDs estables y deduplicacion.
- TradingView ya tiene contrato de señal, 6 fixtures y 6 scripts Pine validados.
- Playbook de estrategia V1 definido para fuentes, frescura, blockers, ranking
  y recomendaciones diarias de revision manual.
- Strategy Intelligence Loop implementado con registry, notas Morgan iniciales,
  validador integrado y cap V31 para estrategias `RADAR_ONLY`.
- Contrato V31 extraido a `v31_contracts.py` con schema versionado para decision
  y contrato seleccionado.
- Compatibilidad V31 entre API, GPT, dashboard y ranking diario cubierta en
  smoke test con fixture dedicado.
- Validacion ejecutable de opciones y prioridad de blockers extraidas a
  `decision_guards.py` con fixture dedicado.
- Gate de production readiness agregado para auth, modo seguro, redaccion,
  limites de email y no-order policy.
- Auditoria redaccionada agregada para decisiones, follow-ups y outcomes, con
  resumen seguro por endpoint.
- Politica de retencion runtime agregada para journals, outcomes y audit log,
  con limites configurables.
- Gate de storage/isolation agregado: multiusuario/comercial queda bloqueado
  sin storage durable, tenant isolation y account isolation.
- Contrato durable storage V1 agregado para Supabase/Postgres: tablas criticas,
  RLS, grants server-side y readiness blocker antes de activar storage durable.
- Adaptador runtime Supabase agregado para journals V32, outcomes y auditoria;
  JSON local sigue como modo personal por defecto.
- Read-auth middleware agregado para proteger dashboards, GPT/status,
  decisiones, auditoria, readiness, storage y superficies V31/V32 en produccion.
- Riesgo principal: la base local pasa, pero el 100% requiere evidencia de
  broker real, alertas reales, storage durable real y reduccion de rutas legacy.
- Regla de seguridad: no hay ejecucion automatica de ordenes permitida.

## Ruta Al 100%

Definicion de 100% para el estado actual del proyecto: Stock Ultimus queda listo
para uso personal operativo controlado cuando las decisiones V31 sean la fuente
unica, los datos reales de IBKR/TradingView esten validados, V32 persista en
storage durable real y la configuracion de produccion quede protegida. Uso
comercial o multiusuario sigue fuera de alcance hasta compliance review.

| Gate para 100% | Estado actual | Evidencia necesaria | Bloqueo |
| --- | --- | --- | --- |
| 1. V31 como fuente unica de decision | En curso | `app/main.py` sin rutas duplicadas que puedan producir decisiones divergentes; smoke API/GPT/dashboard pasando. | Trabajo de arquitectura local. |
| 2. Snapshot real IBKR sanitizado | Pendiente externo | Capturar snapshot real fuera del repo, sanitizarlo y validar decisiones por ticker sin secretos ni datos de cuenta. | Requiere datos reales de IBKR. |
| 3. Forward test TradingView | Pendiente externo | Cargar Pine Pro V2, emitir alertas reales y confirmar payloads aceptados por `/technical_snapshot`. | Requiere TradingView real. |
| 4. Supabase/Postgres durable activo | Pendiente de configuracion | Aplicar `supabase/durable_storage_contract_v1.sql`, configurar `RUNTIME_STORAGE_MODE=supabase` y validar round-trip real. | Requiere backend real y credenciales seguras. |
| 5. Read-auth/produccion verificada | Pendiente de Render | Configurar `READ_ACCESS_TOKEN`, webhook secret, HTTPS base URL y validar endpoints protegidos en produccion. | Requiere variables de entorno en Render. |
| 6. V33/comercial readiness | Pendiente por diseno | Tenant/account isolation, auditoria exportable, disclosures, risk profiles y legal/compliance review. | No necesario para uso personal; obligatorio antes de multiusuario/comercial. |

Lectura rapida: localmente vamos fuerte; para 100% faltan principalmente
validaciones reales y endurecimiento de produccion.

## Semaforo

| Area | Estado | Evidencia | Siguiente accion |
| --- | --- | --- | --- |
| Bridge IBKR | En progreso | `ibkr_bridge.py` contiene campos V30, calidad de datos, entrypoint/cadencia y guardrails de mercado validados. | Revisar contra datos reales de IBKR cuando haya snapshot runtime. |
| Cloud/FastAPI | En progreso | `app/main.py` expone V31 y V32: decisiones canonicas, historial, follow-ups y outcomes; V31 delega schema a `v31_contracts.py` y smoke valida paridad API/GPT/dashboard/ranking. | Reducir caminos legacy y validar snapshot real sanitizado. |
| Decision/Riesgo | Validado localmente | El guard integral valida prioridad `WAIT_OPTIONS_DATA`, `ENTRY_READY`, estados V31 y reglas de strategy readiness. | Agregar pruebas automatizadas formales si se adopta pytest. |
| Fixtures V30 | Validado | 7 fixtures V30 y 1 snapshot runtime sanitizado pasan con `scripts/check_v30_integrity.py`. | Mantener fixtures sincronizados con cambios de contrato. |
| Outcomes V32 | En progreso | Journaling, IDs estables, deduplicacion, follow-ups, MFE/MAE, resumen de outcomes y adapter Supabase pasan guard local. | Aplicar SQL durable en Supabase/Postgres real antes de despliegue. |
| TradingView | Listo para forward test | 6 signal fixtures y 6 Pine scripts pasan validacion; CANSLIM se conserva como filtro separado. | Cargar scripts Pro V2 y validar alertas reales sanitizadas. |
| Strategy Intelligence | En progreso | `strategy_intelligence.py` comparte registry, timestamps, freshness, score components y daily ranking; `v31_contracts.py` comparte schema; `decision_guards.py` comparte contrato ejecutable y blockers. | Validar contra snapshot real IBKR sanitizado. |
| Seguridad | En progreso | Guardrails locales buscan ordenes automaticas prohibidas, datos sensibles en runtime fixtures, readiness de produccion, auditoria redaccionada, retencion runtime, aislamiento storage, contrato durable storage y read-auth. | Configurar `READ_ACCESS_TOKEN` y aplicar contrato durable a Supabase/Postgres antes de uso multiusuario/comercial. |
| Documentacion | En progreso | Roadmap, contrato V30, contrato de señales, playbook de estrategia, strategy intelligence loop, guias Pine y briefs de agentes existen. | Mantener contratos sincronizados con cada cambio de comportamiento. |

## Progreso Por Version

| Version | Objetivo | Estado |
| --- | --- | --- |
| V29.1 | Prioridad correcta para `WAIT_OPTIONS_DATA` cuando falta contrato ejecutable. | Hecho segun guia del proyecto. |
| V30 | Enriquecer contratos de opciones y bloquear readiness si faltan campos ejecutables. | Validado localmente; falta prueba completa con snapshot real sanitizado. |
| V31 | Consolidar motor canonico de decision y schemas compartidos. | En progreso: contrato API, paths canonicos y publicacion runtime disponibles. |
| V32 | Tracking de outcomes y aprendizaje medible. | En progreso: journaling, follow-ups y outcomes validados localmente. |
| V33 | Preparacion product-grade, multiusuario, auditoria y compliance. | Pendiente. |

## Checklist V30

### Snapshot Contract

- [x] Master snapshot incluye `strike`.
- [x] Master snapshot incluye `expiration`.
- [x] Master snapshot incluye `dte`.
- [x] Master snapshot incluye `bid`.
- [x] Master snapshot incluye `ask`.
- [x] Master snapshot incluye `mid`.
- [x] Master snapshot incluye `spread`.
- [x] Master snapshot incluye `spread_pct`.
- [x] Master snapshot incluye `delta`.
- [x] Campos son JSON-serializables.
- [x] Valores faltantes o invalidos son explicitos para la logica de blockers.

### Decision Logic

- [x] Tecnico confirmado mas contrato faltante devuelve `WAIT_OPTIONS_DATA`.
- [x] Tecnico confirmado mas contrato parcial devuelve `WAIT_OPTIONS_DATA`.
- [x] Falta de confirmacion tecnica devuelve `WAIT_TECHNICAL` cuando no hay blocker de mayor prioridad.
- [x] Contrato completo mas riesgo aprobado puede devolver `ENTRY_READY`.
- [x] Falla de riesgo bloquea `ENTRY_READY`.
- [x] No se introduce envio automatico de ordenes IBKR.

### Cloud/API

- [x] POST de snapshot acepta campos V30.
- [x] Persistencia JSON runtime conserva campos V30.
- [x] Endpoint GPT-facing por ticker expone campos V30 y estado de blocker.
- [x] Dashboard refleja estado API.
- [x] Snapshots antiguos no crashean la app cloud.

### QA

- [x] Fixture cubre ausencia de contrato.
- [x] Fixture cubre contrato parcial.
- [x] Fixture cubre contrato completo.
- [x] Fixture cubre falla de riesgo.
- [x] Fixture cubre `ENTRY_READY`.
- [x] Scripts de validacion documentados.

## Validacion Mas Reciente

Comando:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stock_ultimus_pycache python3 scripts/check_v30_integrity.py
```

Resultado:

- 7 fixtures V30 validados.
- Guardrails de no-auto-order validados.
- 34 archivos Python compilados.
- Bridge entrypoint, cadence y market-state guardrails validados.
- Privacidad de fixtures runtime validada.
- 6 fixtures de señales TradingView validados.
- Strategy Intelligence registry y notas Morgan validadas.
- Fixtures V31 de schema de decision y contrato seleccionado validados.
- Compatibilidad V31 API/GPT/dashboard/ranking validada en endpoint smoke.
- Decision guards compartidos validados para contrato ejecutable y blocker priority.
- Production readiness gates y redaccion validados.
- Audit log redaccionado validado y conectado a V32.
- Runtime retention policy validada.
- Storage isolation gate validado.
- Durable storage contract validado con tablas criticas, RLS y grants.
- Supabase durable runtime adapter validado para journals V32 y audit events.
- Read-auth middleware validado para superficies sensibles de produccion.
- 6 scripts Pine de TradingView validados.
- Fusion por contexto de estrategia y preservacion CANSLIM validadas.
- Reglas de strategy readiness validadas.
- Metadata de legacy compatibility y paridad de ingest validadas.
- Journaling y outcomes V32 validados.
- Estados canonicos V31 validados en rutas v27/v27.1/v28.
- Escenarios guard V29 validados.
- Snapshot runtime sanitizado validado para 5 tickers.
- Endpoint smoke V29/V31 validado.
- Resultado final: `V30 integrity check passed`.

Comando:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/stock_ultimus_pycache python3 scripts/validate_v30_fixtures.py
```

Resultado:

- 7 fixtures V30 validados.
- Guardrails de no-auto-order validados.

Nota: Python emitio un warning de `urllib3`/LibreSSL durante el integrity check.
No bloqueo la validacion.

## Riesgos Y Decisiones Abiertas

| Riesgo | Impacto | Mitigacion |
| --- | --- | --- |
| Multiples motores historicos en `app/main.py`. | Puede crear estados inconsistentes entre dashboard, API y GPT. | Usar V31 como contrato canonico y reducir caminos legacy restantes. |
| Falta de snapshots runtime reales en repo. | La validacion local puede no cubrir peculiaridades de IBKR en vivo. | Capturar snapshots sanitizados y agregarlos como fixtures. |
| Journals V32 usan persistencia runtime local por defecto. | En local sigue siendo volatil; en produccion requiere backend durable real. | Aplicar SQL `durable_storage_contract_v1` en Supabase/Postgres y configurar `RUNTIME_STORAGE_MODE=supabase`. |
| Scope comercial/multiusuario bloqueado por diseño. | Evita uso prematuro con datos de terceros. | Habilitar solo con contrato durable aplicado, tenant isolation, account isolation y compliance review. |
| Pine scripts aun no tienen forward test real. | La sintaxis local puede pasar mientras alertas reales difieren por simbolo o timeframe. | Probar Pro V2 en TradingView con payloads sanitizados antes de confiar en la señal. |
| Seguridad para uso comercial/multiusuario pendiente. | Riesgo de exposicion de datos, credenciales o cuentas. | No avanzar a comercial sin auth, aislamiento, audit logs, disclosures y compliance review. |
| Readiness de produccion puede bloquear despliegue si faltan secretos o URL. | Es intencional: evita correr con config insegura. | Configurar `DEPLOYMENT_ENV`, tokens, webhook secret, HTTPS base URL y limites de email en Render. |
| Read endpoints sensibles requieren token en produccion. | Sin `READ_ACCESS_TOKEN`, dashboards/GPT/status quedan bloqueados. | Configurar `READ_ACCESS_TOKEN` en Render y usar header `X-Stock-Ultimus-Read-Token`. |
| Manual review puede confundirse con autorizacion de operar. | Riesgo operativo si se interpreta `ENTRY_READY` como orden. | Mantener copy y schemas: `ENTRY_READY` significa listo para revision manual. |
| Playbook/registry/ranking/frescura, schema V31, compatibilidad de superficies y decision guards ya tienen fixtures. | Falta validacion con datos runtime reales sanitizados. | Capturar snapshot IBKR real sanitizado. |
| Investigacion de traders top puede confundirse con copy-trading. | Riesgo operativo y de compliance si se replican trades o se elimina criterio propio. | Morgan debe convertir practicas externas en hipotesis testeables; nunca en instrucciones ni overrides. |

## Proximas Acciones Para Cerrar El 100%

1. Reducir caminos historicos de decision en `app/main.py` hasta que V31 sea la
   fuente unica de verdad.
2. Capturar un snapshot real de IBKR fuera del repo, sanitizarlo con
   `scripts/sanitize_runtime_snapshot.py` y validar decisiones por ticker.
3. Cargar Pine Pro V2 en TradingView y hacer forward test contra
   `/technical_snapshot`.
4. Aplicar `supabase/durable_storage_contract_v1.sql` en Supabase/Postgres real.
5. Configurar `READ_ACCESS_TOKEN`, webhook secret, HTTPS base URL y limites de
   email en Render.
6. Activar `RUNTIME_STORAGE_MODE=supabase` y validar round-trip real de journals,
   outcomes y audit events.
7. Mantener V33 como bloqueado para multiusuario/comercial hasta tener
   aislamiento, disclosures y compliance review.

## Registro De Avances

| Fecha | Cambio | Evidencia |
| --- | --- | --- |
| 2026-06-11 | Se crea tablero de proyecto y se registra estado V30 actual. | `scripts/check_v30_integrity.py` y `scripts/validate_v30_fixtures.py` pasan. |
| 2026-06-11 | Se agrega version visual HTML del tablero. | `docs/project-dashboard.html`. |
| 2026-06-12 | Se agrega snapshot runtime sanitizado multi-ticker. | `fixtures/runtime/v28_master_snapshot_sanitized.json` validado por `scripts/check_v30_integrity.py`. |
| 2026-06-12 | Se agrega sanitizador y validador de privacidad para snapshots reales. | `scripts/sanitize_runtime_snapshot.py` y `scripts/validate_runtime_privacy.py`. |
| 2026-06-17 | Se inicia V31 como contrato canonico versionado sobre V29. | `/v31_system_status`, `/v31_trade_decision/{ticker}`, `/gpt_v31_trade_decision/{ticker}` y `scripts/check_v30_integrity.py` pasan. |
| 2026-06-18 | Se valida el primer flujo V32 de decision journaling y outcomes. | `scripts/check_v32_outcomes_tracking.py` pasa integrado al guard V30. |
| 2026-06-18 | Se agregan contratos y señales de estrategia para TradingView. | 6 fixtures de señal y 6 scripts Pine pasan validacion local. |
| 2026-06-18 | Se amplian guardrails de compatibilidad y reglas de estrategia. | Fusion por contexto, CANSLIM, legacy parity y strategy readiness pasan. |
| 2026-06-19 | Se define playbook operativo de estrategias V1. | `docs/strategy-playbook.md` documenta fuentes, frescura, blockers, ranking y recomendaciones manual-review por estrategia. |
| 2026-06-19 | Se define Strategy Intelligence Loop V1. | `docs/strategy-intelligence-loop.md` formaliza como Morgan convierte mercado, traders top e instituciones en hipotesis testeables y reglas versionadas. |
| 2026-06-19 | Se implementa registry y notas Morgan iniciales. | `config/strategy_registry.json`, `docs/strategy_research_notes/` y `scripts/validate_strategy_intelligence.py` pasan en `scripts/check_v30_integrity.py`. |
| 2026-06-19 | V31 consume el strategy registry. | Estrategias `RADAR_ONLY` no pueden salir como `ENTRY_READY`; se degradan a `MANUAL_REVIEW` con `STRATEGY_RADAR_ONLY`. |
| 2026-06-19 | V31 expone score components. | `strategy_score_components_v1` calcula tecnico, opcion, riesgo, fundamental/CANSLIM, regimen, outcome evidence y registry. |
| 2026-06-19 | V31 expone ranking diario. | `strategy_daily_ranking_v1` separa `top_manual_review`, `watchlist`, `blocked` y `research_only`. |
| 2026-06-19 | V31 expone freshness gates. | `freshness_gates_v1` penaliza ranking por fuentes stale/unknown y evita top manual-review con datos criticos viejos. |
| 2026-06-19 | V31 conecta timestamps de contexto. | `source_context_timestamps_v1` conserva timestamps de IBKR, fundamental/CANSLIM y account context sin exponer datos sensibles. |
| 2026-06-19 | Strategy Intelligence se extrae a modulo compartido. | `strategy_intelligence.py` concentra registry, source context, freshness, scoring y daily ranking. |
| 2026-06-19 | Schema V31 se extrae a modulo compartido. | `v31_contracts.py` define `v31_decision_contract_schema_v1` y `selected_contract_v1`; fixture V31 valida registry caps y no-order flag. |
| 2026-06-19 | Compatibilidad de superficies V31 validada. | `fixtures/v31/surface_compatibility_cases.json` y `scripts/smoke_v29_endpoints.py` comparan API, GPT, dashboard y ranking diario. |
| 2026-06-19 | Decision guards extraidos. | `decision_guards.py` centraliza contrato ejecutable, riesgo manual y prioridad de blockers; `scripts/validate_decision_guards.py` pasa en el guard integral. |
| 2026-06-19 | Production readiness gate agregado. | `production_readiness.py`, `/production_readiness` y `scripts/validate_production_readiness.py` bloquean config insegura sin exponer secretos. |
| 2026-06-19 | Auditoria redaccionada agregada. | `audit_log.py`, `/audit_log_summary` y `scripts/validate_audit_log.py` registran decisiones/follow-ups/outcomes sin exponer secretos. |
| 2026-06-19 | Retencion runtime agregada. | `runtime_retention.py`, `/runtime_retention` y `scripts/validate_runtime_retention.py` aplican limites configurables a journals/outcomes/audit logs. |
| 2026-06-19 | Storage isolation gate agregado. | `storage_isolation.py`, `/storage_isolation` y `scripts/validate_storage_isolation.py` bloquean scope comercial/multiusuario sin storage durable y aislamiento. |
| 2026-06-19 | Durable storage contract agregado. | `durable_storage.py`, `/durable_storage_contract` y `scripts/validate_durable_storage.py` definen tablas criticas, RLS, grants y blockers para Supabase/Postgres. |
| 2026-06-19 | Supabase runtime adapter agregado. | V32 decisions/outcomes/audit events pueden persistir via Supabase REST; `scripts/check_durable_storage_runtime.py` valida round-trip offline. |
| 2026-06-19 | Read-auth middleware agregado. | `READ_ACCESS_TOKEN` protege dashboards, GPT/status, decisiones, auditoria, readiness y V31/V32; `scripts/check_read_auth_gate.py` valida la compuerta. |
| 2026-06-19 | Se agregan fixtures de freshness por fuente. | `fixtures/strategy_intelligence/freshness_cases.json` cubre IBKR, TradingView, market regime, CANSLIM/fundamental y account context fresh/stale. |
| 2026-06-22 | Se actualiza tablero con ruta explicita al 100%. | `scripts/check_v30_integrity.py` pasa: V30/V31/V32, TradingView, bridge guardrails, storage, read-auth y endpoint smoke validados localmente. |
| 2026-06-23 | Se refresca tablero con corte diario. | `scripts/check_v30_integrity.py` vuelve a pasar; siguen abiertos los mismos gates reales para 100%: V31 unico, IBKR real, TradingView real, Supabase real y Render protegido. |
