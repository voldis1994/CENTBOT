# CENTBOT

Autonomous paid-task workstation: discover → analyze → execute → verify → submit → account rewards.

Default mode is **`dry_run`** (no live accepts, no real money movement). Live mode requires explicit config and API keys.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# No-money-risk demo (items 89–94 scaffolding)
python -m centbot --demo

# Single cycle
python -m centbot --once

# 24/7 loop + dashboard http://127.0.0.1:8787
./scripts/start.sh            # Windows: START.bat
./scripts/stop.sh             # Windows: STOP.bat
```

## Layout

| Path | Purpose |
|------|---------|
| `centbot/core` | Engine, SQLite, config, monitor, recovery, priority, parallel pool, backup, emergency stop |
| `centbot/platforms` | Jobbi, BasedAgents, TaskMarket, BountyBook, Agentizable + extra sources |
| `centbot/discovery` | Global scanner, new-task watcher, dedup |
| `centbot/analysis` | Availability, funding, trust, category, complexity, ETA, cost, EV profit, reject/accept |
| `centbot/executors` | CSV, Excel, JSON/XML, PDF, image, text, programming + tests |
| `centbot/browser` | Playwright automation + allow-listed scraping |
| `centbot/android` | ADB, emulator mgmt, gestures, screenshots, app testing |
| `centbot/ai` | Ollama client, analyzer, planner, decomposer, workers |
| `centbot/finance` | Bank/crypto ledger, FX, fees, withdrawals (manual approve), optimization |
| `centbot/dashboard` | Control panel API/UI |
| `START.bat` / `STOP.bat` | Windows control |
| `scripts/start.sh` / `stop.sh` | Unix control |

## Safety

- Credentials encrypted at rest (`data/credentials.enc`); never commit secrets.
- Withdrawals require manual approval.
- Web fetch only for allow-listed hosts + `robots.txt`.
- Untrusted code runs in a subprocess sandbox under `sandbox/`.
- Emergency stop: create `data/EMERGENCY_STOP` or use dashboard button.

## Tests

```bash
pytest -q
```
