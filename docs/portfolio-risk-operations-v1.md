# Operación automatizada de riesgo de cartera v1

## Propósito

Mantener actualizado el diagnóstico multicuenta, administrar el ciclo de vida de sus alertas y preparar avisos y resúmenes locales. Esta capa no coloca órdenes, no liquida posiciones y no envía información a servicios externos.

## Ciclo operativo

El runner `scripts/run_portfolio_risk_operations.py` dispone de tres modos:

- `monitor`: dentro de la ventana configurada puede refrescar TWS en modo de lectura, reevaluar riesgo, actualizar el outbox y generar el digest;
- `preflight`: valida política, snapshots, alertas, acciones humanas y outbox sin consultar el broker salvo que se solicite explícitamente;
- `digest`: genera el resumen local vigente.

La configuración está en `config/portfolio_risk_operations.json`. La zona horaria predeterminada es `America/New_York`, la ventana es 07:00–17:30 en días laborables y el monitor programado se despierta cada cinco minutos.

## Acciones humanas

Cada alerta activa puede administrarse desde la consola:

- **Confirmar 4 h**: registra que fue revisada y evita avisos repetidos durante cuatro horas;
- **Silenciar 60 min**: suspende temporalmente avisos de esa alerta;
- **Reabrir ahora**: cancela la confirmación o silencio vigente.

La severidad y el estado global de riesgo no se reducen por confirmar una alerta. La acción sólo modifica su estado operativo y elegibilidad de notificación.

Si la severidad cambia, cualquier confirmación o silencio previo deja de aplicar y la alerta vuelve a abrirse automáticamente.

Las acciones se guardan en `runtime/portfolio_risk_actions.json`, con actor, razón, vencimiento y contador de cambios. Sólo pueden modificarse IDs de alerta actualmente activos.

## Outbox y escalamiento

El outbox local vive en `runtime/portfolio_risk_outbox.json`.

- Sólo `CRITICAL` y `HIGH` son notificables por defecto.
- Una alerta pendiente no se duplica.
- El cooldown predeterminado es de 60 minutos.
- Una `CRITICAL` abierta escala después de 15 minutos.
- Una `HIGH` abierta escala después de 60 minutos.
- Las alertas confirmadas o silenciadas no ingresan al outbox mientras la acción esté vigente.
- Si una alerta deja de ser notificable, su mensaje pendiente se cancela antes de cualquier entrega.

El canal predeterminado es `LOCAL_OUTBOX`. No existe envío de email, webhook o Pushover en esta versión.

## Notificaciones locales

Notification Center de macOS es opt-in. El runner sólo lo utiliza con `--local-notify` o cuando `local_notifications_enabled` se cambia explícitamente a `true`.

La instalación programada tampoco activa avisos por defecto. Para incluirlos deliberadamente:

```bash
python3 scripts/install_portfolio_risk_launchd.py --install --enable-local-notifications
```

## Digest

Cada ciclo genera:

- `runtime/portfolio_risk_digest_latest.json`;
- `runtime/portfolio_risk_digest_latest.md`.

El digest incluye estado, decisión, score, alertas abiertas/confirmadas/silenciadas, notificaciones pendientes y las prioridades con su siguiente paso.

## Programación local

El instalador `scripts/install_portfolio_risk_launchd.py` define tres jobs sin secretos:

- monitor cada 300 segundos;
- digest diario a las 17:35;
- preflight diario a las 07:00.

Siempre revisar primero:

```bash
python3 scripts/install_portfolio_risk_launchd.py --install --dry-run
```

Los jobs no se consideran activos hasta que sus tres archivos estén instalados en `~/Library/LaunchAgents`.
El runner usa un lock no bloqueante para impedir que dos ciclos modifiquen simultáneamente snapshots, outbox o digest.

## Guardrails

- IDs reales de broker excluidos.
- Sin tokens ni secretos en plist, outbox, digest o estado.
- Notificaciones externas desactivadas.
- Notificaciones macOS opt-in.
- Escrituras atómicas.
- `execution_authorized=false`.
- `automatic_liquidation_authorized=false`.
- `not_order_instruction=true`.
