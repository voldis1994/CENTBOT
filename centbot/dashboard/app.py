"""CENTBOT main control panel (Flask) — Latvian live ops UI."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, render_template_string

from centbot.dashboard.portutil import pick_port
from centbot.runtime_paths import bundle_root, install_root

_panel_candidates = (
    Path(__file__).with_name("panel.html"),
    bundle_root() / "centbot" / "dashboard" / "panel.html",
    install_root() / "centbot" / "dashboard" / "panel.html",
)
PANEL_PATH = next((p for p in _panel_candidates if p.exists()), _panel_candidates[0])
DASHBOARD_HTML = PANEL_PATH.read_text(encoding="utf-8") if PANEL_PATH.exists() else "<h1>CENTBOT</h1>"


def _dashboard_state_path() -> Path:
    return install_root() / "data" / "runtime" / "dashboard.json"


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


def write_dashboard_state(host: str, port: int, *, extra: dict[str, Any] | None = None) -> Path:
    path = _dashboard_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": host,
        "port": port,
        "url": f"http://{'127.0.0.1' if host in {'0.0.0.0', '::'} else host}:{port}/",
        **(extra or {}),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def read_dashboard_state() -> dict[str, Any]:
    path = _dashboard_state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def start_dashboard_thread(app: Flask, host: str, port: int) -> threading.Thread:
    """Bind preferred port or next free port; never crash on 'address already in use'."""
    choice = pick_port(host, int(port or 8787))
    if not choice.get("ok"):
        raise OSError(f"dashboard_no_free_port preferred={port}")
    chosen = int(choice["port"])
    write_dashboard_state(
        host,
        chosen,
        extra={"preferred": int(port or 8787), "bumped": bool(choice.get("bumped")), "reason": choice.get("reason")},
    )

    def _run() -> None:
        # use_reloader=False — reloader would fork a second process and confuse ports
        app.run(host=host, port=chosen, threaded=True, use_reloader=False)

    t = threading.Thread(target=_run, daemon=True, name="centbot-dashboard")
    t.start()
    return t

