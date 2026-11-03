"""CENTBOT main control panel (Flask) — Latvian live ops UI."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, render_template_string

PANEL_PATH = Path(__file__).with_name("panel.html")
DASHBOARD_HTML = PANEL_PATH.read_text(encoding="utf-8")


def create_dashboard(
    get_status: Callable[[], dict[str, Any]],
    emergency_stop: Callable[[], None],
    *,
    ack_alert: Callable[[int], bool] | None = None,
    update_settings: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Flask:
    app = Flask("centbot_dashboard")

    @app.get("/")
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.get("/api/status")
    def status():
        return jsonify(get_status())

    @app.post("/api/emergency-stop")
    def stop():
        emergency_stop()
        return jsonify({"ok": True})

    @app.post("/api/ack-alert/<int:alert_id>")
    def ack(alert_id: int):
        if ack_alert is None:
            return jsonify({"ok": False, "error": "ack_unavailable"}), 501
        return jsonify({"ok": bool(ack_alert(alert_id)), "id": alert_id})

    @app.post("/api/settings")
    def settings():
        from flask import request

        if update_settings is None:
            return jsonify({"ok": False, "error": "settings_unavailable"}), 501
        payload = request.get_json(silent=True) or {}
        return jsonify(update_settings(payload))

    return app


def start_dashboard_thread(app: Flask, host: str, port: int) -> threading.Thread:
    t = threading.Thread(
        target=lambda: app.run(host=host, port=port, threaded=True, use_reloader=False),
        daemon=True,
    )
    t.start()
    return t
