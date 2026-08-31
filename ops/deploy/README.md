# ops/deploy — the arb-vm deploy rail `[C-DEPLOY-01]` `[G-DEPLOY-01]`

`edit locally → Jenkins green → merge to main → arb-vm runs the new SHA within one poll.`

Everything real runs here. The laptop holds code and fixtures only (rule 14).

## Provenance

Ported from `../past/convexity ops/deploy/autodeploy.sh @ d7a733a8dcf6` (**SAL-0010**, decision
PORT), which was written for a fleet trading real money. Its four safety properties are kept:

1. **The running stack is never taken down for a build.** Images build under the new SHA tag;
   services move only after the build is green. A failed build leaves the current containers
   running and returns the checkout to where it was.
2. **Trading-path services never restart mid-session** — the market-hours guard, below.
3. **The checkout is never force-reset.** `--ff-only`; divergence stops the deploy loudly
   rather than silently discarding work.
4. **Failures alert and stop.** No partial promotion, no retry storm — the next timer tick is
   the retry, which is why the unit sets `Restart=no`.

**What we changed, and why it is the interesting part.** The donor's mid-cycle guard ran
`pgrep` inside a container with no `procps`. The command exited 127, the caller read that as
"not busy", and the one guard whose entire purpose was to avoid restarting mid-trade was inert
— while looking perfectly healthy. pips' guard is therefore a separate program whose **exit
code is the answer**, and every uncertainty resolves to *defer*: an unknown service is treated
as trading-path, an unreadable calendar blocks, and an exception inside the guard blocks. A
guard that cannot answer must never answer "yes". `tests/unit/test_deploy_guard.py` pins each
of those cases.

## The market-hours guard (§2.2)

| service class | services | behaviour |
|---|---|---|
| research / data | `research-runner`, `backfill`, `telemetry` | roll immediately on every main update |
| trading path | `breeze-reader`, `shadow-engine`, `live-engine` | held during **08:45–15:35 IST** on a trading day |
| anything else | — | **treated as trading-path** (fail closed) |

The window is wider than the continuous session at both ends deliberately: a reader that must
be warm at 09:15 cannot be restarting at 09:10, and the closing auction runs to 15:35 even
though the continuous tape stops at 15:30.

A human may force an intraday restart (`sync.sh --force`). §2.2 requires a forced restart to
follow the crash-recovery path like any other — journal replay, then broker reconciliation,
before any new risk is admitted (§3.13) — and the guard's own output says so.

## VM bootstrap

Run once, on arb-vm. Requires sudo.

```bash
# 1. Docker engine + compose plugin (Ubuntu 24.04)
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update -qq
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu     # log out and back in for this to take effect

# 2. Data root and state. ALL market data and runtime state live here, never in the repo.
sudo install -d -o ubuntu -g ubuntu /srv/pips /srv/pips/deploy /srv/pips/secrets
sudo install -d -o ubuntu -g ubuntu -m 0700 /srv/pips/secrets
sudo install -d -o ubuntu -g ubuntu /srv/pips/{bronze,silver,gold,quarantine,snapshots,universes}

# 3. Read-only repo access. The keypair is generated ON the VM so the private half never
#    travels; add ONLY the public half to GitHub, as a deploy key with write access OFF.
ssh-keygen -t ed25519 -N "" -C "pips-deploy@arb-vm (read-only)" -f ~/.ssh/pips_deploy
cat ~/.ssh/pips_deploy.pub      # -> GitHub repo -> Settings -> Deploy keys -> Add
# ~/.ssh/config already routes `github-pips` through that key (IdentitiesOnly yes).

# 4. Build checkout — a dedicated clone the rail owns. Never develop in it.
git clone git@github-pips:prateekrastogi/pips.git /srv/pips/checkout

# 5. VM-side secrets. ORDER-PLANE credentials only — rule 7 keeps the planes apart, and the
#    Breeze data-plane token rides in the repo's .env instead (ADR-0011).
cat > /srv/pips/secrets/deploy.env <<'ENV'
# PIPS_EXPECTED_SERVICES="breeze-reader shadow-engine"   # set once M4+ services exist
# PIPS_ALERT_CMD=/usr/local/bin/notify                    # optional; log-only if unset
ENV
chmod 600 /srv/pips/secrets/deploy.env

# 6. The timer
sudo cp /srv/pips/checkout/ops/deploy/pips-deploy.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pips-deploy.timer
systemctl list-timers pips-deploy.timer
```

## Operating it

```bash
ops/deploy/sync.sh                 # one poll by hand
ops/deploy/sync.sh --force         # override the market-hours guard (a human act)
ops/deploy/rollback.sh <sha>       # manual revert; obeys the same guard
journalctl -u pips-deploy -f       # what the rail is doing
cat /srv/pips/deploy/last-good-sha # the SHA a failed health check rolls back to
```

## The health check is deliberately not a stub that passes

`healthcheck.sh` asserts the services named in `PIPS_EXPECTED_SERVICES` are `running`. When
that variable is unset it says so **loudly and exits 0** — at M3.5 the `vm` profile is still
stubs, so there is genuinely nothing to assert. What it must never become is a check that
returns success while verifying nothing, because that converts "we verified the deploy" into a
sentence nobody checked. Set the variable as soon as M4 lands a real service.

## What this rail cannot do

It cannot start live trading. The live-flag chain (rule 8) needs the engine compiled with the
`live` feature, `PIPS_LIVE=1` set by a human on this VM, and a config carrying
`i_understand_live_trading: true` — none of which the rail touches. A code deploy can never
silently change live behaviour; only a new signed bundle can.
