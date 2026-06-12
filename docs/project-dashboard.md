# Stock Ultimus Project Dashboard

Ultima actualizacion: 2026-06-11

Este tablero es el punto vivo para saber como vamos. Cada vez que avancemos en
codigo, fixtures, documentacion o validacion, se debe actualizar esta pagina con
el nuevo estado, evidencia y siguiente accion.

Vista visual amigable: `docs/project-dashboard.html`.

## Estado Ejecutivo

Estado actual: V30 en verificacion e integracion.

Resumen:

- Prioridad activa: V30 Contract Enrichment.
- Objetivo: publicar contratos ejecutables con campos completos y preservar
  `WAIT_OPTIONS_DATA` antes de cualquier `ENTRY_READY`.
- Validacion local: pasando.
- Riesgo principal: hay multiples caminos historicos de decision en
  `app/main.py`; V31 debe consolidar una sola fuente canonica.
- Regla de seguridad: no hay ejecucion automatica de ordenes permitida.

## Semaforo

| Area | Estado | Evidencia | Siguiente accion |
| --- | --- | --- | --- |
| Bridge IBKR | En progreso | `ibkr_bridge.py` contiene campos V30, calidad de datos y validacion de contrato ejecutable. | Revisar contra datos reales de IBKR cuando haya snapshot runtime. |
| Cloud/FastAPI | En progreso | `app/main.py` expone estados V30 y campos de contrato en endpoints/dashboard. | Consolidar decision canonica en V31. |
| Decision/Riesgo | Validado localmente | `scripts/check_v30_integrity.py` valida prioridad `WAIT_OPTIONS_DATA`, `ENTRY_READY` y guardrails. | Agregar pruebas automatizadas formales si se adopta pytest. |
| Fixtures V30 | Validado | 7 fixtures V30 y 1 snapshot runtime sanitizado pasan con `scripts/check_v30_integrity.py`. | Mantener fixtures sincronizados con cambios de contrato. |
| Seguridad | Alineado | Guardrail local busca patrones de orden automatica prohibida. | Endurecer auth, logs y aislamiento antes de uso multiusuario/comercial. |
| Documentacion | En progreso | Roadmap, contrato V30, checklist y briefs de agentes existen. | Marcar checklist de aceptacion con evidencia por item. |

## Progreso Por Version

| Version | Objetivo | Estado |
| --- | --- | --- |
| V29.1 | Prioridad correcta para `WAIT_OPTIONS_DATA` cuando falta contrato ejecutable. | Hecho segun guia del proyecto. |
| V30 | Enriquecer contratos de opciones y bloquear readiness si faltan campos ejecutables. | En verificacion/integracion. |
| V31 | Consolidar motor canonico de decision y schemas compartidos. | Pendiente. |
| V32 | Tracking de outcomes y aprendizaje medible. | Pendiente. |
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
- 6 archivos Python compilados.
- Escenarios guard V29 validados.
- Snapshot runtime sanitizado validado para 5 tickers.
- Endpoint smoke V29 validado.
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
| Multiples motores historicos en `app/main.py`. | Puede crear estados inconsistentes entre dashboard, API y GPT. | V31 debe centralizar el motor canonico. |
| Falta de snapshots runtime reales en repo. | La validacion local puede no cubrir peculiaridades de IBKR en vivo. | Capturar snapshots sanitizados y agregarlos como fixtures. |
| Seguridad para uso comercial/multiusuario pendiente. | Riesgo de exposicion de datos, credenciales o cuentas. | No avanzar a comercial sin auth, aislamiento, audit logs, disclosures y compliance review. |
| Manual review puede confundirse con autorizacion de operar. | Riesgo operativo si se interpreta `ENTRY_READY` como orden. | Mantener copy y schemas: `ENTRY_READY` significa listo para revision manual. |

## Proximas Acciones

1. Probar V30 con un snapshot real capturado desde IBKR y sanitizado antes de commit.
2. Crear pruebas automatizadas formales alrededor del motor V29/V30 si el proyecto adopta pytest.
3. Iniciar V31: una decision canonica, schema compartido y una sola prioridad de blockers.
4. Ampliar fixtures runtime para casos reales raros detectados por Vega/Ledger.

## Registro De Avances

| Fecha | Cambio | Evidencia |
| --- | --- | --- |
| 2026-06-11 | Se crea tablero de proyecto y se registra estado V30 actual. | `scripts/check_v30_integrity.py` y `scripts/validate_v30_fixtures.py` pasan. |
| 2026-06-11 | Se agrega version visual HTML del tablero. | `docs/project-dashboard.html`. |
| 2026-06-12 | Se agrega snapshot runtime sanitizado multi-ticker. | `fixtures/runtime/v28_master_snapshot_sanitized.json` validado por `scripts/check_v30_integrity.py`. |
