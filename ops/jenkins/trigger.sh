#!/usr/bin/env bash
# Trigger the pips-ci job for a ref and wait for its verdict.
#
# Usage:  ops/jenkins/trigger.sh [ref]      (or: make jenkins-build REF=m/0-scaffold)
#
# There is no poll, no timer and no push hook on this controller: a build exists because
# someone asked for one on a named ref. That keeps the build history a record of deliberate
# merge decisions rather than a stream of background noise.
set -euo pipefail

# TMPDIR, not a hardcoded /tmp: some sandboxes deny /tmp writes, and curl then fails to
# open its cookie jar and exits before the request is ever made — which reads as an auth or
# network fault rather than a filesystem one.
WORK="${TMPDIR:-/tmp}"

REF="${1:-main}"
URL="${JENKINS_URL:-http://127.0.0.1:8081}"
USER_ID="${JENKINS_USER:-pips}"
TOKEN="${JENKINS_TOKEN:-${PIPS_JENKINS_PASSWORD:-pips-local-only}}"
AUTH=(-u "${USER_ID}:${TOKEN}")

crumb() {
  curl -fsS "${AUTH[@]}" --cookie-jar "${WORK}/pips-jenkins-cookies" \
    "${URL}/crumbIssuer/api/json" | jq -r '.crumbRequestField + ":" + .crumb'
}

echo "pips-ci: requesting build of ref '${REF}' at ${URL}"
CRUMB="$(crumb)"

QUEUE_URL="$(curl -fsS -X POST "${AUTH[@]}" --cookie "${WORK}/pips-jenkins-cookies" \
  -H "${CRUMB}" -D - -o /dev/null \
  "${URL}/job/pips-ci/buildWithParameters?PIPS_REF=$(printf '%s' "$REF" | jq -sRr @uri)" \
  | awk 'tolower($1)=="location:"{print $2}' | tr -d '\r')"

if [ -z "${QUEUE_URL}" ]; then
  echo "pips-ci: no queue location returned — is the job created and the controller up?" >&2
  exit 1
fi
echo "pips-ci: queued at ${QUEUE_URL}"

# The queue item becomes a build; poll until it does, then follow the build to a verdict.
BUILD_URL=""
for _ in $(seq 1 120); do
  BUILD_URL="$(curl -fsS "${AUTH[@]}" "${QUEUE_URL}api/json" | jq -r '.executable.url // empty')"
  [ -n "${BUILD_URL}" ] && break
  sleep 2
done
[ -n "${BUILD_URL}" ] || { echo "pips-ci: build never left the queue" >&2; exit 1; }
echo "pips-ci: building at ${BUILD_URL}"

RESULT="null"
for _ in $(seq 1 900); do
  RESULT="$(curl -fsS "${AUTH[@]}" "${BUILD_URL}api/json" | jq -r '.result // "null"')"
  [ "${RESULT}" != "null" ] && break
  sleep 2
done

echo "───────── console tail ─────────"
curl -fsS "${AUTH[@]}" "${BUILD_URL}consoleText" | tail -40
echo "────────────────────────────────"
echo "pips-ci: ${REF} -> ${RESULT}   (${BUILD_URL})"
[ "${RESULT}" = "SUCCESS" ]
