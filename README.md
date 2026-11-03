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

## Quick start

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
./scripts/start.sh   # Windows: START.bat
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
