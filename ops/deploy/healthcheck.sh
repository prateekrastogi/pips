#!/usr/bin/env bash
# pips deploy rail — post-deploy health check. Non-zero exit triggers auto-rollback.
#
# Deliberately shallow at M3.5 and deliberately NOT a stub that always passes: a health check
# that cannot fail is worse than none, because it converts "we verified the deploy" into a
# statement nobody checked. Today it verifies the containers a service-set should be running
# are actually up; M23 adds the engine's own readiness (risk state machine reaching READY
# after journal replay and broker reconciliation).
set -uo pipefail

REPO="${PIPS_REPO:-/srv/pips/checkout}"
COMPOSE_FILE="${PIPS_COMPOSE:-$REPO/docker-compose.yml}"
EXPECTED="${PIPS_EXPECTED_SERVICES:-}"

log() { echo "[pips-health $(date -u +%FT%TZ)] $*"; }

# Nothing is expected to be running yet at M3.5 (the compose 'vm' profile is stubs), so an
# empty expectation is legitimate — but it must be stated explicitly, not inferred from an
# empty query result.
if [ -z "$EXPECTED" ]; then
  log "PIPS_EXPECTED_SERVICES is unset — no service-level health assertions to make."
  log "Set it in the VM env file once M4+ services exist, or this check proves nothing."
  exit 0
fi

failed=0
for service in $EXPECTED; do
  state="$(docker compose -f "$COMPOSE_FILE" ps --format '{{.Service}} {{.State}}' 2>/dev/null \
            | awk -v s="$service" '$1==s {print $2}')"
  if [ "$state" != "running" ]; then
    log "UNHEALTHY $service: state='${state:-absent}'"
    failed=1
  else
    log "ok $service"
  fi
done
exit "$failed"
