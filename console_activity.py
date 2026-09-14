"""Build the non-operational activity feed from local evidence."""
from typing import Any, Callable


ALERT_ACTION_LABELS = {
    "ACK_ALERT": "Alerta marcada como vista",
    "REVIEWING": "Alerta en revisión",
    "WATCH": "Alerta en seguimiento",
    "REJECT": "Alerta descartada por el operador",
    "CLOSE": "Seguimiento de alerta cerrado",
    "MARK_IBKR_APPLIED": "Ejecución informada; pendiente de conciliación",
    "MARK_NOT_APPLIED": "Decisión de no ejecutar registrada",
    "MARK_MISSED": "Oportunidad no aplicada registrada",
}


def build_activity_rows(
    tasks: list[dict[str, Any]],
    position_reviews: list[dict[str, Any]],
    alert_events: list[dict[str, Any]],
    refresh_report: dict[str, Any],
    futures_events: list[dict[str, Any]],
    *,
    friendly_state: Callable[[Any, str], str],
    lifecycle_state: Callable[[dict[str, Any]], dict[str, Any]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    task_labels = {"DONE": "Revisado por hoy", "POSTPONED": "Revisión pospuesta", "REVIEWING": "En revisión", "NEW": "Pendiente"}
    for record in tasks:
        if not isinstance(record, dict):
            continue
        rows.append({"at": str(record.get("updated_at") or ""), "type": "task", "title": str(record.get("title") or "Revisión diaria"),
                     "detail": task_labels.get(str(record.get("state") or ""), "Estado registrado")})
    for record in position_reviews:
        if not isinstance(record, dict):
            continue
        rows.append({"at": str(record.get("recorded_at") or ""), "type": "position", "title": str(record.get("ticker") or "Posición"),
                     "detail": "Revisión de posición registrada; no confirma una ejecución"})
    for record in alert_events:
        if not isinstance(record, dict):
            continue
        action = str(record.get("action") or "").upper()
        rows.append({"at": str(record.get("recorded_at") or ""), "type": "alert", "title": str(record.get("ticker") or "Alerta"),
                     "detail": ALERT_ACTION_LABELS.get(action, friendly_state(record.get("operator_status") or action, "Acción de alerta registrada"))})
    if refresh_report.get("generated_at"):
        status = str(refresh_report.get("status") or "").upper()
        detail = "Actualización completa de fuentes" if status in {"OK", "COMPLETE", "COMPLETED"} else "Actualización parcial; revisar fuentes pendientes" if status == "PARTIAL" else "La actualización de fuentes requiere revisión"
        rows.append({"at": str(refresh_report["generated_at"]), "type": "data", "title": "Datos de la consola", "detail": detail})
    seen = set()
    for event in futures_events:
        if not isinstance(event, dict):
            continue
        lifecycle = str((lifecycle_state(event) or {}).get("lifecycle_state") or "").upper()
        if lifecycle not in {"EXPIRED", "STALE", "CLOSED"}:
            continue
        key = str(event.get("event_id") or event.get("alert_id") or "{}|{}".format(event.get("ticker"), event.get("received_at")))
        if key in seen:
            continue
        seen.add(key)
        rows.append({"at": str(event.get("received_at") or event.get("generated_at") or ""), "type": "signal",
                     "title": str(event.get("ticker") or event.get("symbol") or "Futuro"),
                     "detail": "Señal vencida; se conserva como actividad y no como oportunidad vigente"})
    return rows
