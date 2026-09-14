from datetime import datetime, timezone
import unittest

import console_activity


def friendly(value, fallback):
    return str(value or fallback)


def lifecycle(event):
    return {"lifecycle_state": event.get("lifecycle_state")}


class ConsoleActivityTests(unittest.TestCase):
    def test_combines_local_activity_without_treating_live_signal_as_history(self):
        now = datetime.now(timezone.utc).isoformat()
        rows = console_activity.build_activity_rows(
            [{"updated_at": now, "title": "Riesgo", "state": "DONE"}],
            [{"recorded_at": now, "ticker": "RSP"}],
            [{"recorded_at": now, "ticker": "MNQ", "action": "ACK_ALERT"}],
            {"generated_at": now, "status": "PARTIAL"},
            [
                {"event_id": "expired", "ticker": "MES", "received_at": now, "lifecycle_state": "EXPIRED"},
                {"event_id": "live", "ticker": "MNQ", "received_at": now, "lifecycle_state": "LIVE"},
            ],
            friendly_state=friendly,
            lifecycle_state=lifecycle,
        )
        self.assertEqual({row["type"] for row in rows}, {"task", "position", "alert", "data", "signal"})
        self.assertTrue(any("Actualización parcial" in row["detail"] for row in rows))
        self.assertTrue(any(row["title"] == "MES" and "no como oportunidad" in row["detail"] for row in rows))
        self.assertFalse(any(row["title"] == "MNQ" and row["type"] == "signal" for row in rows))

    def test_deduplicates_expired_signal_and_omits_refresh_without_timestamp(self):
        event = {"event_id": "same", "ticker": "MNQ", "received_at": "2026-01-01T00:00:00Z", "lifecycle_state": "STALE"}
        rows = console_activity.build_activity_rows([], [], [], {"status": "OK"}, [event, event], friendly_state=friendly, lifecycle_state=lifecycle)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "signal")

