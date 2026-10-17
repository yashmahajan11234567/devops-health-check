"""devops-health-check: minimal Flask health service.

Two endpoints served by gunicorn on 0.0.0.0:8000:

- GET /health  -> liveness. Always 200 while the process can respond.
- GET /ready   -> readiness. Gated on env APP_READY (default "true");
                  returns 503 while not ready so k8s can stop routing traffic.
"""

import os
from datetime import datetime, timezone

from flask import Flask, jsonify

APP_VERSION = "0.1.0"

_TRUE_VALUES = {"true", "1", "yes"}


def _app_name() -> str:
    return os.environ.get("APP_NAME", "devops-health-check")


def _is_ready() -> bool:
    return os.environ.get("APP_READY", "true").strip().lower() in _TRUE_VALUES


def create_app() -> Flask:
    """Application factory; env vars are read per-request so tests can flip them."""
    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify(
            service=_app_name(),
            version=APP_VERSION,
            status="healthy",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @app.get("/ready")
    def ready():
        if _is_ready():
            return jsonify(ready=True)
        return jsonify(ready=False, reason="APP_READY is not enabled"), 503

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover - convenience only; gunicorn is the server
    app.run(host="0.0.0.0", port=int(os.environ.get("APP_PORT", "8000")))
