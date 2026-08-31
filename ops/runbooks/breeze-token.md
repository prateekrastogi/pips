# Runbook — daily Breeze session token

The Breeze session token expires daily. Under ADR-0011 it lives in the tracked `.env` in this
private repository, so rotating it is a commit.

## Procedure

1. Generate a fresh session token from the Breeze developer portal for the API key in `.env`.
2. Paste it into `.env` as `BREEZE_SESSION_TOKEN=…`. Change nothing else.
3. Commit and push:

```bash
git add .env && git commit -m "chore: rotate breeze session token" && git push
```

4. On arb-vm the deploy rail picks up the new main SHA within a poll interval and restarts the
   research/data services with it. **Trading-path services do not restart during market
   hours** (§2.2) — if the token expires mid-session and `breeze-reader` needs it, that is an
   incident, not a routine deploy: follow the market-hours forced-restart path (journal replay
   plus broker reconciliation, §3.13) rather than waiting for the rail.

## Rotate early, not at 09:14

The token's daily expiry and the market open are hours apart, and the failure mode of a stale
token is a data plane that comes up blind. Rotate before the session, not during it.

## What must never happen

- **Never put an order-plane credential in this file.** Rule 7 keeps the two planes in
  separate processes with separate credentials; broker secrets stay in the VM-side env file
  the order adapter reads. `.env` is the data plane only.
- **Never let `.env` into an image.** `.dockerignore` excludes it, no Dockerfile copies it, and
  `tests/unit/test_secrets_and_data_locality.py` fails the build if either changes. That half
  of rule 14 is untouched by ADR-0011.
- **Never set `PIPS_LIVE` here.** The live-flag chain is a human act on arb-vm and is outside
  the loop's authority by construction (rule 8).

## If the repository's audience ever widens

Making this repo public, adding collaborators, or forking it means **every historical token in
git history is disclosed** — rotating today's does not remove yesterday's from past commits.
Rotate the Breeze credentials first and treat all past tokens as compromised. ADR-0011 records
the encrypted-at-rest option (sops/age) as the upgrade path; adopting it does not require
undoing ADR-0011, only re-encrypting.
