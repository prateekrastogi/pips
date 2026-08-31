#!/usr/bin/env bash
# pips deploy rail — best-effort alerting. NEVER fails the deploy because a notification did.
#
# Wraps the harvested donor (SAL-0010 sibling: convexity scripts/fleet_alert.sh, WRAP) rather
# than reimplementing it. Configure a channel by setting PIPS_ALERT_CMD in the VM env file to
# any command that takes the message as its single argument; unset means log-only.
set -uo pipefail
MSG="${1:?usage: alert.sh <message>}"
echo "[pips-alert $(date -u +%FT%TZ)] $MSG"
[ -n "${PIPS_ALERT_CMD:-}" ] && { $PIPS_ALERT_CMD "pips: $MSG" >/dev/null 2>&1 || true; }
exit 0
