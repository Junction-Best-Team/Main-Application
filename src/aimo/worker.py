"""Independent, durable chat worker. No public API and no browser session keys."""

import logging
import signal
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

from aimo import conversations
from aimo.config import settings
from aimo.db import close_pools, connection
from aimo.service import Service

log = logging.getLogger(__name__)


def run_once(service, runner=None):
    turn = conversations.claim_turn()
    if turn is None:
        return False
    conversations.execute_turn(turn, service, runner)
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    stop = Event()
    state = {"ready": False, "progress": time.monotonic()}

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            fresh = time.monotonic() - state["progress"] < 270
            healthy = fresh and (self.path == "/health/live" or state["ready"])
            code = (
                (200 if healthy else 503) if self.path in ("/health/live", "/health/ready") else 404
            )
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b"ok" if code == 200 else b"not ready")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", 8001), Health)
    Thread(target=server.serve_forever, daemon=True).start()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    try:
        from aimo.search import model, model_key

        if settings().embedding_backend == "sentence_transformers":
            model()
        service = Service()
        while not stop.is_set():
            try:
                with connection() as c:
                    active = c.execute(
                        "SELECT g.model_key FROM active_catalog a JOIN catalog_generations g ON g.id=a.generation"
                    ).fetchone()
                    c.execute("SELECT requested_by FROM conversation_turns LIMIT 0")
                if not active or active["model_key"] != model_key():
                    raise RuntimeError("Catalog/model mismatch")
                state.update(ready=True, progress=time.monotonic())
                worked = run_once(service)
                state["progress"] = time.monotonic()
                if not worked:
                    stop.wait(1)
            except Exception as exc:
                # Do not log customer messages, provider payloads or connection URLs.
                log.warning("Worker iteration failed (%s)", type(exc).__name__)
                state["ready"] = False
                stop.wait(2)
    finally:
        state["ready"] = False
        server.shutdown()
        close_pools()


if __name__ == "__main__":
    main()
