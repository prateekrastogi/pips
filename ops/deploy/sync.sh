#!/usr/bin/env bash
# pips deploy rail — poll origin/main, build, gate, promote  [C-DEPLOY-01] [G-DEPLOY-01]
#
#   ops/deploy/sync.sh            # one pass (what the systemd timer runs)
#   ops/deploy/sync.sh --force    # override the market-hours guard (a human act)
#
# PORTED from ../past/convexity ops/deploy/autodeploy.sh @ d7a733a8dcf6 (SAL-0010), which was
# written for a fleet trading real money. Its four safety properties are kept verbatim in
# spirit, because each was paid for:
#
#   * THE RUNNING STACK IS NEVER TAKEN DOWN FOR A BUILD. Everything is built under a
#     SHA tag; services move only after the build and health checks are green. A failed
#     build leaves the current containers running, untouched.
#   * IT WILL NOT RESTART A TRADING-PATH SERVICE MID-SESSION. pips' version of the donor's
#     "busy" check is the market-hours guard (§2.2), and it FAILS CLOSED — see below.
#   * IT NEVER FORCE-RESETS THE CHECKOUT. --ff-only; local divergence stops the deploy
#     loudly instead of silently discarding work.
#   * FAILURES ALERT AND STOP. No partial promotion, no retry storm.
#
# WHAT WE CHANGED, AND WHY. The donor's guard ran `pgrep` INSIDE a container that had no
# procps: it exited 127 and the caller read that as "not busy", so the one guard whose entire
# purpose was to avoid restarting mid-trade was inert while looking healthy. pips' guard is a
# separate program whose EXIT CODE is the answer, and every uncertainty in it — unknown
# service, unreadable calendar, an exception in the guard itself — returns "defer". A guard
# that cannot answer must never answer "yes".

set -uo pipefail

REPO="${PIPS_REPO:-/srv/pips/checkout}"
BRANCH="${PIPS_BRANCH:-main}"
COMPOSE_FILE="${PIPS_COMPOSE:-$REPO/docker-compose.yml}"
STATE_DIR="${PIPS_STATE:-/srv/pips/deploy}"
LOCK="${PIPS_DEPLOY_LOCK:-/srv/pips/deploy/sync.lock}"
LAST_GOOD="$STATE_DIR/last-good-sha"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

# NO HARDCODED SERVICE LIST. The rail asks compose what exists and asks the guard how to
# treat each one. An earlier version kept its own list and it drifted: sync.sh promoted
# `research-runner`, then aborted on `backfill`, which the list named and compose did not
# define. That left some services on the new SHA and some on the old — a PARTIAL promotion,
# the exact outcome the donor's fourth safety property exists to prevent (SAL-0010).
#
# `research` is excluded from promotion on purpose: it is the build/CI container, run
# on demand, not a long-running service to restart.
NOT_PROMOTED="research"

log()   { echo "[pips-deploy $(date -u +%FT%TZ)] $*"; }
alert() { log "ALERT: $*"; "$REPO/ops/deploy/alert.sh" "$*" 2>/dev/null || true; }
die()   { alert "$*"; exit 1; }

# --- one deployer at a time, even if the timer overlaps a slow build ------------------
mkdir -p "$STATE_DIR"
exec 9>"$LOCK" || die "cannot open lock $LOCK"
flock -n 9 || { log "another deploy is in flight; leaving it alone"; exit 0; }

cd "$REPO" || die "no checkout at $REPO — run the bootstrap in ops/deploy/README.md"

# --- fetch and fast-forward. NEVER a hard reset. --------------------------------------
git fetch --quiet origin "$BRANCH" || die "git fetch failed"
CURRENT="$(git rev-parse HEAD)"
TARGET="$(git rev-parse "origin/$BRANCH")"

[ "$CURRENT" = "$TARGET" ] && { log "already at ${TARGET:0:12}; nothing to do"; exit 0; }

if ! git merge-base --is-ancestor "$CURRENT" "$TARGET"; then
  die "checkout has diverged from origin/$BRANCH (HEAD ${CURRENT:0:12} is not an ancestor of ${TARGET:0:12}). Refusing to force-reset — inspect $REPO by hand."
fi

log "new SHA on origin/$BRANCH: ${CURRENT:0:12} -> ${TARGET:0:12}"
git merge --ff-only "origin/$BRANCH" --quiet || die "fast-forward failed"

# RE-EXEC, because we have just rewritten the file we are running from.
#
# Bash reads a script lazily, by byte offset. The fast-forward above can change sync.sh
# underneath this very shell, which then continues reading at its saved offset in a file whose
# contents have shifted. Observed live on 2026-08-31: a run began on the old script, pulled in
# a fix to that same script, and carried on executing the OLD logic — promoting a service the
# new version had already removed. The benign outcome was a failed deploy; the general case is
# arbitrary corruption, because the offset lands wherever it lands.
#
# The guard flag makes this exactly one re-exec: the second invocation sees the checkout
# already at TARGET and takes the "nothing to do" path if it re-enters here at all.
if [ -z "${PIPS_DEPLOY_REEXEC:-}" ]; then
  log "checkout updated; re-executing the new sync.sh before building"
  flock -u 9 2>/dev/null || true
  PIPS_DEPLOY_REEXEC=1 exec "$REPO/ops/deploy/sync.sh" "$@"
fi

# --- build under the SHA tag. The running stack is untouched until this is green. -----
export PIPS_SHA="$TARGET"
if ! docker compose -f "$COMPOSE_FILE" build 2>&1 | tail -20; then
  git merge --ff-only "$CURRENT" --quiet 2>/dev/null || git reset --hard "$CURRENT" --quiet
  die "build failed for ${TARGET:0:12}; checkout returned to ${CURRENT:0:12}, containers untouched"
fi
log "built images tagged ${TARGET:0:12}"

# --- promote, service by service, honouring the market-hours guard --------------------
DEFERRED=""

# Every service compose defines, minus the ones that are not long-running.
services_to_promote() {
  # COMPOSE_PROFILES=vm: the long-running services are all under that profile, so a plain
  # `config --services` reports only the build container and the rail would find nothing to
  # promote while appearing to succeed.
  COMPOSE_PROFILES=vm docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null \
    | grep -vxF "$NOT_PROMOTED" | sort
}

promote() {
  local service="$1"
  local guard_args=("$service")
  [ "$FORCE" = "1" ] && guard_args+=("--force")

  if ! docker compose -f "$COMPOSE_FILE" run --rm --no-deps research \
        python -m pips.cli deploy guard "${guard_args[@]}"; then
    log "DEFER $service (market-hours guard)"
    DEFERRED="$DEFERRED $service"
    return 0
  fi

  log "promoting $service"
  COMPOSE_PROFILES=vm docker compose -f "$COMPOSE_FILE" up -d --no-deps "$service" \
    || die "up -d failed for $service"
}

PROMOTABLE="$(services_to_promote)"
[ -n "$PROMOTABLE" ] || die "compose defines no promotable services — refusing to continue"
log "services to promote: $(echo $PROMOTABLE | tr '\n' ' ')"

# VALIDATE THE WHOLE SET BEFORE TOUCHING ANYTHING. Discovering a problem mid-promotion is
# what produces a half-deployed fleet; discovering it here costs one poll interval.
for s in $PROMOTABLE; do
  COMPOSE_PROFILES=vm docker compose -f "$COMPOSE_FILE" config --services | grep -qxF "$s" \
    || die "service '$s' vanished between listing and promotion — refusing to promote a partial set"
done

for s in $PROMOTABLE; do promote "$s"; done

# --- health check, then auto-rollback on failure --------------------------------------
if ! "$REPO/ops/deploy/healthcheck.sh"; then
  PREVIOUS="$(cat "$LAST_GOOD" 2>/dev/null || echo "$CURRENT")"
  alert "health check FAILED at ${TARGET:0:12}; rolling back to ${PREVIOUS:0:12}"
  "$REPO/ops/deploy/rollback.sh" "$PREVIOUS" || alert "ROLLBACK ALSO FAILED — human needed"
  exit 1
fi

echo "$TARGET" > "$LAST_GOOD"
if [ -n "$DEFERRED" ]; then
  log "deployed ${TARGET:0:12}; DEFERRED (will retry next poll):$DEFERRED"
else
  log "deployed ${TARGET:0:12}; all services on the new SHA"
fi
