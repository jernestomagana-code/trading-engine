"""Log bounded memory observations around the scheduled Render workload."""

import itertools
import json
import os
import time

from runtime_liveness import memory_usage


ROUTES = frozenset({
    "/decision_desk/ingest",
    "/gpt_v32_operator_today",
    "/outcomes",
    "/technical_snapshot",
    "/v28_ingest_snapshot",
    "/v31_ingest_snapshot",
    "/v31_manual_reviews",
    "/v31_system_status",
    "/v32_decisions",
    "/v32_intraday_futures_reconcile",
    "/v32_signal_events",
})


class RenderCycleMemoryMiddleware:
    def __init__(self, app):
        self.app = app
        self.ids = itertools.count(1)

    async def __call__(self, scope, receive, send):
        route = scope.get("path")
        if scope["type"] != "http" or route not in ROUTES:
            return await self.app(scope, receive, send)

        request_id = next(self.ids)
        start = time.monotonic()
        status = None
        body_bytes = 0

        def record(phase):
            memory = memory_usage()
            print("render_cycle_memory " + json.dumps({
                "pid": os.getpid(),
                "id": request_id,
                "route": route,
                "phase": phase,
                "status": status,
                "body_bytes": body_bytes,
                "elapsed_ms": round((time.monotonic() - start) * 1000),
                "rss": memory["process_rss_bytes"],
                "peak_rss": memory["process_peak_rss_bytes"],
                "container_bytes": memory["container_current_bytes"],
            }, separators=(",", ":")), flush=True)

        async def observe_receive():
            nonlocal body_bytes
            message = await receive()
            if message["type"] == "http.request":
                body_bytes += len(message.get("body", b""))
            return message

        async def observe_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                record("response")
            await send(message)

        record("start")
        try:
            await self.app(scope, observe_receive, observe_send)
        finally:
            record("finish")
