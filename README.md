# CENTBOT

Autonomous paid-task workstation on **live** platform APIs (no demo catalogs).

Default `system.mode` is `dry_run`: real discovery + local execution, **no** claims/submits.  
Set `mode: live` and `analysis.auto_accept: true` plus platform credentials for real claims.

## Live platforms

| Platform | Base URL | Auth |
|----------|----------|------|
| Jobbi | `https://jobbi.org/gigs.json` | none (index only; claim on origin board) |
| BasedAgents | `https://api.basedagents.ai` | Ed25519 AgentSig keypair |
| TaskMarket | `https://api.taskmarket.dev` | Ethereum EIP-191 wallet |
| BountyBook | `https://api.bountybook.ai` | Bearer + wallet |
| Agentizable | `https://api.agentizable.ai` | discovery live; claim via first-party auth URL |

## Quick start (Windows)

```bat
SETUP.bat          REM hardware check, venv, Git, Playwright, Docker/WSL, Android SDK/AVDs, wizard
START.bat          REM engine + up to 4 Android emulators + control panel
STOP.bat           REM stop CENTBOT engine + managed emulators only
```

`SETUP.bat` is resumable (`data/setup/progress.json`), skips components that already work, and never stores bank passwords / CVV / seed phrases.  
First run opens the configuration wizard → writes `config/local.yaml`.  
Default Android AVDs: `CENTBOT_ANDROID_01` … `_04` (count reduced automatically if RAM/CPU is insufficient).

Control panel: http://127.0.0.1:8787/

## Quick start (Linux / macOS)

```bash
pip install -r requirements.txt

# Verify live feeds
python -m centbot --integrations
python -m centbot --discover

# Local practice on real listings (no claims)
python -m centbot --demo

# Register BasedAgents identity (saves keypair)
python -m centbot --register-basedagents MyCentBot --keypair data/basedagents-keypair.json

# 24/7
./scripts/start.sh
```

Copy `config/local.yaml.example` → `config/local.yaml` for live keys and `mode: live`.

## Safety

- Never commit private keys. Use env vars / `data/credentials.enc`.
- Withdrawals require manual approval.
- Jobbi/Agentizable claims are handoff-only where the platform requires human wallet confirmation.
- Emergency stop: `data/EMERGENCY_STOP` or dashboard button.

## Tests

```bash
pytest -q
```

Linux/macOS pytest covers bootstrap **logic** (wizard validation, progress resume, distributor, secret refusals).  
It is **not** evidence that Windows SETUP/AVD install succeeded — that requires a real Windows run of `SETUP.bat` / `START.bat`.
