#!/usr/bin/env bash
# pips deploy rail — revert to a known SHA  [G-DEPLOY-01]
#
#   ops/deploy/rollback.sh <sha>            # called by sync.sh on a failed health check
#   ops/deploy/rollback.sh <sha> --force    # human override of the market-hours guard
#
# A rollback is a restart, so it obeys the SAME market-hours guard as a deploy: reverting a
# trading-path service mid-session is exactly as disruptive as upgrading one, and "it is a
# rollback" is not a reason to skip journal replay and broker reconciliation (§3.13).
#
# The one asymmetry: if the health check failed because a trading-path service is BROKEN,
# leaving it broken until 15:35 is worse than restarting it. That call is a human's — pass
# --force, and the crash-recovery path applies.

set -uo pipefail

SHA="${1:?usage: rollback.sh <sha> [--force]}"
FORCE=0
[ "${2:-}" = "--force" ] && FORCE=1

REPO="${PIPS_REPO:-/srv/pips/checkout}"
COMPOSE_FILE="${PIPS_COMPOSE:-$REPO/docker-compose.yml}"

log() { echo "[pips-rollback $(date -u +%FT%TZ)] $*"; }

cd "$REPO" || { log "no checkout at $REPO"; exit 1; }
git rev-parse --verify "$SHA^{commit}" >/dev/null 2>&1 || { log "unknown SHA $SHA"; exit 1; }

log "rolling back to ${SHA:0:12}"
git checkout --quiet --detach "$SHA" || { log "checkout failed"; exit 1; }

export PIPS_SHA="$SHA"
# Images for a previous SHA are usually still in the local cache; build is a no-op then, and
# a rebuild if they were pruned. Either way the tag is what the compose file resolves.
docker compose -f "$COMPOSE_FILE" build 2>&1 | tail -5

for service in research-runner backfill telemetry breeze-reader shadow-engine live-engine; do
  guard_args=("$service"); [ "$FORCE" = "1" ] && guard_args+=("--force")
  if docker compose -f "$COMPOSE_FILE" run --rm --no-deps research \
       python -m pips.cli deploy guard "${guard_args[@]}"; then
    docker compose -f "$COMPOSE_FILE" up -d --no-deps "$service" || log "up -d failed: $service"
  else
    log "DEFER $service (market-hours guard) — pass --force if it is broken and cannot wait"
  fi
done
log "rollback to ${SHA:0:12} complete"
