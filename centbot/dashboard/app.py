"""Central workstation control panel (Flask)."""

from __future__ import annotations

import threading
from typing import Any, Callable

from flask import Flask, jsonify, render_template_string

DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>CENTBOT Control Panel</title>
  <style>
    :root {
      --bg0: #0b1412;
      --bg1: #12201c;
      --ink: #e7f2ec;
      --muted: #8fa89c;
      --accent: #3dba84;
      --warn: #e0a045;
      --danger: #d45d5d;
      --line: rgba(231,242,236,.12);
      --font-display: "Fraunces", "Iowan Old Style", Georgia, serif;
      --font-body: "IBM Plex Sans", "Segoe UI", sans-serif;
    }
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
    * { box-sizing: border-box; }
    body {
      margin: 0; color: var(--ink); font-family: var(--font-body);
      background:
        radial-gradient(1000px 500px at 10% -10%, rgba(61,186,132,.18), transparent 55%),
        radial-gradient(800px 400px at 90% 0%, rgba(224,160,69,.12), transparent 50%),
        linear-gradient(165deg, var(--bg0), var(--bg1) 45%, #0e1815);
      min-height: 100vh;
    }
    header {
      padding: 2rem 2rem 1rem; border-bottom: 1px solid var(--line);
    }
    .brand {
      font-family: var(--font-display); font-size: clamp(2rem, 4vw, 3rem);
      letter-spacing: .02em; margin: 0;
    }
    .sub { color: var(--muted); margin: .4rem 0 0; max-width: 40rem; }
    main { padding: 1.25rem 2rem 2.5rem; display: grid; gap: 1rem; }
    .grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
    .panel {
      border: 1px solid var(--line); border-radius: 14px; padding: 1rem 1.1rem;
      background: rgba(255,255,255,.03); backdrop-filter: blur(6px);
    }
    .panel h2 { margin: 0 0 .75rem; font-size: .85rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); font-weight: 600; }
    .metric { font-family: var(--font-display); font-size: 1.8rem; }
    .muted { color: var(--muted); font-size: .9rem; }
    table { width: 100%; border-collapse: collapse; font-size: .92rem; }
    th, td { text-align: left; padding: .45rem .3rem; border-bottom: 1px solid var(--line); }
    .ok { color: var(--accent); }
    .warn { color: var(--warn); }
    .bad { color: var(--danger); }
    button {
      background: var(--accent); color: #062016; border: 0; border-radius: 999px;
      padding: .55rem 1rem; font-weight: 600; cursor: pointer;
    }
    button.danger { background: var(--danger); color: white; }
  </style>
</head>
<body>
  <header>
    <h1 class="brand">CENTBOT</h1>
    <p class="sub">Centrālais darba stacijas vadības panelis — reāllaika uzdevumi, finanses un sistēmas brīdinājumi.</p>
  </header>
  <main>
    <div class="grid">
      <section class="panel"><h2>Mode</h2><div class="metric" id="mode">-</div><div class="muted" id="cycle">cycle -</div></section>
      <section class="panel"><h2>Active workers</h2><div class="metric" id="workers">0</div><div class="muted" id="workerIds"></div></section>
      <section class="panel"><h2>Tasks</h2><div class="metric" id="tasks">0</div><div class="muted" id="taskBreakdown"></div></section>
      <section class="panel"><h2>Profit</h2><div class="metric" id="profit">0</div><div class="muted" id="currency"></div></section>
    </div>
    <section class="panel">
      <h2>System</h2>
      <div id="system" class="muted">Loading…</div>
    </section>
    <section class="panel">
      <h2>Alerts</h2>
      <div id="alerts" class="muted">None</div>
      <p style="margin-top:1rem">
        <button class="danger" onclick="fetch('/api/emergency-stop',{method:'POST'}).then(refresh)">Emergency stop</button>
      </p>
    </section>
    <section class="panel">
      <h2>Recent tasks</h2>
      <table><thead><tr><th>Title</th><th>Platform</th><th>Status</th><th>Profit</th></tr></thead><tbody id="taskRows"></tbody></table>
    </section>
  </main>
  <script>
    async function refresh() {
      const s = await fetch('/api/status').then(r => r.json());
      document.getElementById('mode').textContent = s.mode;
      document.getElementById('cycle').textContent = 'cycles ' + s.cycles;
      document.getElementById('workers').textContent = s.workers.active;
      document.getElementById('workerIds').textContent = (s.workers.ids || []).join(', ');
      document.getElementById('tasks').textContent = s.tasks.total;
      document.getElementById('taskBreakdown').textContent =
        `eligible ${s.tasks.eligible} · running ${s.tasks.running} · done ${s.tasks.completed} · rejected ${s.tasks.rejected}`;
      document.getElementById('profit').textContent = Number(s.finance.profit).toFixed(2);
      document.getElementById('currency').textContent = s.finance.currency;
      const snap = s.system || {};
      document.getElementById('system').innerHTML =
        `CPU ${snap.cpu_percent ?? '-'}% · RAM ${snap.ram_percent ?? '-'}% · net ${snap.internet_ok ? '<span class=ok>ok</span>' : '<span class=bad>down</span>'}`;
      document.getElementById('alerts').innerHTML = (s.alerts || []).map(a =>
        `<div class="${a.level==='critical'?'bad':(a.level==='warning'?'warn':'')}">${a.message}</div>`).join('') || 'None';
      document.getElementById('taskRows').innerHTML = (s.recent_tasks || []).map(t =>
        `<tr><td>${t.title||''}</td><td>${t.platform||''}</td><td>${t.status||''}</td><td>${Number(t.expected_profit||0).toFixed(2)}</td></tr>`).join('');
    }
    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>
"""


def create_dashboard(get_status: Callable[[], dict[str, Any]], emergency_stop: Callable[[], None]) -> Flask:
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

    return app


def start_dashboard_thread(app: Flask, host: str, port: int) -> threading.Thread:
    t = threading.Thread(target=lambda: app.run(host=host, port=port, threaded=True, use_reloader=False), daemon=True)
    t.start()
    return t
