#!/usr/bin/env bash
# Trigger the pips-ci job for a ref and wait for its verdict.
#
# Usage:  ops/jenkins/trigger.sh [ref]      (or: make jenkins-build REF=m/0-scaffold)
#
# There is no poll, no timer and no push hook on this controller: a build exists because
# someone asked for one on a named ref. That keeps the build history a record of deliberate
# merge decisions rather than a stream of background noise.
set -euo pipefail

# EXIT CODES. A single non-zero exit made "the build failed" and "the controller was
# unreachable" indistinguishable, and the pre-push hook printed `pips-ci is RED` for a `curl`
# connection reset while Jenkins was restarting. A gate that FAILED and a gate that COULD NOT
# RUN need different responses: fix the code, versus retry or check the controller. Both still
# block the push -- only the diagnosis differs.
UNREACHABLE=3

unreachable() {
  echo "pips-ci: could not reach the controller at ${URL} -- THE GATE DID NOT RUN." >&2
  echo "         $1" >&2
  exit "${UNREACHABLE}"
}

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
CRUMB="$(crumb)" || unreachable "the crumb request failed; is the controller up?"

QUEUE_URL="$(curl -fsS -X POST "${AUTH[@]}" --cookie "${WORK}/pips-jenkins-cookies" \
  -H "${CRUMB}" -D - -o /dev/null \
  "${URL}/job/pips-ci/buildWithParameters?PIPS_REF=$(printf '%s' "$REF" | jq -sRr @uri)" \
  | awk 'tolower($1)=="location:"{print $2}' | tr -d '\r')" \
  || unreachable "the build request failed"

if [ -z "${QUEUE_URL}" ]; then
  unreachable "no queue location returned — is the job created?"
fi
echo "pips-ci: queued at ${QUEUE_URL}"

# The queue item becomes a build; poll until it does, then follow the build to a verdict.
BUILD_URL=""
for _ in $(seq 1 120); do
  # `|| true`: a transport blip mid-poll is not a verdict. The loop retries; only running out
  # of attempts is conclusive, and that is reported as "did not run" rather than as red.
  BUILD_URL="$(curl -fsS "${AUTH[@]}" "${QUEUE_URL}api/json" 2>/dev/null \
    | jq -r '.executable.url // empty' || true)"
  [ -n "${BUILD_URL}" ] && break
  sleep 2
done
[ -n "${BUILD_URL}" ] || unreachable "the build never left the queue"
echo "pips-ci: building at ${BUILD_URL}"

RESULT="null"
for _ in $(seq 1 900); do
  # Same reasoning: the controller restarting mid-build is a blip to ride out, not a red build.
  RESULT="$(curl -fsS "${AUTH[@]}" "${BUILD_URL}api/json" 2>/dev/null \
    | jq -r '.result // "null"' || true)"
  [ -n "${RESULT}" ] && [ "${RESULT}" != "null" ] && break
  sleep 2
done
if [ -z "${RESULT}" ] || [ "${RESULT}" = "null" ]; then
  unreachable "the build produced no verdict within the wait"
fi

echo "───────── console tail ─────────"
curl -fsS "${AUTH[@]}" "${BUILD_URL}consoleText" 2>/dev/null | tail -40 || true
echo "────────────────────────────────"
echo "pips-ci: ${REF} -> ${RESULT}   (${BUILD_URL})"
[ "${RESULT}" = "SUCCESS" ]
