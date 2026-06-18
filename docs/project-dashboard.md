# Stock Ultimus Project Dashboard

Ultima actualizacion: 2026-06-18

Este tablero es el punto vivo para saber como vamos. Cada vez que avancemos en
codigo, fixtures, documentacion o validacion, se debe actualizar esta pagina con
el nuevo estado, evidencia y siguiente accion.

Vista visual amigable: `docs/project-dashboard.html`.

## Estado Ejecutivo

Estado actual: V30 validado localmente; V31 y V32 activos con guardrails; integracion TradingView lista para forward test.

Resumen:

- Prioridad activa: V31 Canonical Decision Contract.
- Objetivo: exponer una decision canonica versionada sobre el motor validado,
  con blockers, contrato seleccionado, riesgo, explicacion y no-order guardrails.
- Validacion local: pasando para V30, V31, V32 y señales TradingView.
- V32 ya registra decisiones, follow-ups y outcomes con IDs estables y deduplicacion.
- TradingView ya tiene contrato de señal, 6 fixtures y 6 scripts Pine validados.
- Riesgo principal: hay multiples caminos historicos de decision en
  `app/main.py`; V31 ya expone contrato canonico, pero falta extraer schemas/modulos compartidos.
- Regla de seguridad: no hay ejecucion automatica de ordenes permitida.

## Semaforo

| Area | Estado | Evidencia | Siguiente accion |
| --- | --- | --- | --- |
| Bridge IBKR | En progreso | `ibkr_bridge.py` contiene campos V30, calidad de datos y validacion de contrato ejecutable. | Revisar contra datos reales de IBKR cuando haya snapshot runtime. |
| Cloud/FastAPI | En progreso | `app/main.py` expone V31 y V32: decisiones canonicas, historial, follow-ups y outcomes. | Extraer contrato/schemas fuera de `app/main.py`. |
| Decision/Riesgo | Validado localmente | El guard integral valida prioridad `WAIT_OPTIONS_DATA`, `ENTRY_READY`, estados V31 y reglas de strategy readiness. | Agregar pruebas automatizadas formales si se adopta pytest. |
| Fixtures V30 | Validado | 7 fixtures V30 y 1 snapshot runtime sanitizado pasan con `scripts/check_v30_integrity.py`. | Mantener fixtures sincronizados con cambios de contrato. |
| Outcomes V32 | En progreso | Journaling, IDs estables, deduplicacion, follow-ups, MFE/MAE y resumen de outcomes pasan el guard local. | Definir persistencia productiva, retencion y auditoria antes de despliegue. |
| TradingView | Listo para forward test | 6 signal fixtures y 6 Pine scripts pasan validacion; CANSLIM se conserva como filtro separado. | Cargar scripts Pro V2 y validar alertas reales sanitizadas. |
| Seguridad | Alineado | Guardrails locales buscan ordenes automaticas prohibidas y datos sensibles en runtime fixtures. | Endurecer auth, logs y aislamiento antes de uso multiusuario/comercial. |
| Documentacion | En progreso | Roadmap, contrato V30, contrato de señales, guias Pine y briefs de agentes existen. | Mantener contratos y tablero sincronizados con cada cambio de comportamiento. |

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
- 16 archivos Python compilados.
- Privacidad de fixtures runtime validada.
- 6 fixtures de señales TradingView validados.
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
| Multiples motores historicos en `app/main.py`. | Puede crear estados inconsistentes entre dashboard, API y GPT. | Usar V31 como contrato canonico y extraer schemas/modulos compartidos. |
| Falta de snapshots runtime reales en repo. | La validacion local puede no cubrir peculiaridades de IBKR en vivo. | Capturar snapshots sanitizados y agregarlos como fixtures. |
| Journals V32 usan persistencia runtime local. | Puede perderse historia o mezclarse contexto sin una politica productiva. | Definir almacenamiento durable, retencion, aislamiento y auditabilidad. |
| Pine scripts aun no tienen forward test real. | La sintaxis local puede pasar mientras alertas reales difieren por simbolo o timeframe. | Probar Pro V2 en TradingView con payloads sanitizados antes de confiar en la señal. |
| Seguridad para uso comercial/multiusuario pendiente. | Riesgo de exposicion de datos, credenciales o cuentas. | No avanzar a comercial sin auth, aislamiento, audit logs, disclosures y compliance review. |
| Manual review puede confundirse con autorizacion de operar. | Riesgo operativo si se interpreta `ENTRY_READY` como orden. | Mantener copy y schemas: `ENTRY_READY` significa listo para revision manual. |

## Proximas Acciones

1. Extraer contrato V31 a modulos compartidos (`decision schema`, `contract schema`, `blocker priority`) para reducir `app/main.py`.
2. Capturar un snapshot real de IBKR fuera del repo y pasarlo por `scripts/sanitize_runtime_snapshot.py`.
3. Hacer forward test de los Pine Pro V2 y confirmar alertas contra `/technical_snapshot`.
4. Diseñar persistencia durable y auditada para journals/outcomes V32.

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
