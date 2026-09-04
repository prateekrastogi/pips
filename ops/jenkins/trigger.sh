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

# THREE STATES, NOT TWO. The exit-code note above splits a build that FAILED from a gate that
# COULD NOT RUN. A third state hid between them: the gate is WAITING. `pips-ci` builds one at a
# time, so a push made while another build is in flight finds its item BLOCKED -- and the
# controller is demonstrably reachable, because it is the very thing answering the poll that
# reports the block. Calling that "could not reach the controller" sent this session to probe a
# controller that was up the whole time and answering 200.
still_queued() {
  echo "pips-ci: the build is STILL QUEUED after ${QUEUE_WAIT}s -- THE GATE DID NOT RUN." >&2
  echo "         This is NOT an unreachable controller. It is answering, and it reports:" >&2
  echo "           $1" >&2
  echo "         pips-ci builds one at a time. Let the build in flight finish, then push again." >&2
  exit "${UNREACHABLE}"
}

# A MISSING TOOL IS NOT AN UNREACHABLE CONTROLLER. Without `jq`, the crumb pipeline "fails" and
# this script reported "the crumb request failed; is the controller up?" -- sending the reader to
# check a controller that was fine. Jenkins build #276 failed exactly that way: the CI image
# installs curl but not jq. That is the third instance of one shape in this one file, so the
# check goes FIRST, before any claim about anything the script cannot see.
for tool in curl jq awk; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    echo "pips-ci: '${tool}' is not installed -- THE GATE DID NOT RUN." >&2
    echo "         Nothing was contacted and nothing is known about the controller." >&2
    echo "         Install ${tool} and run again." >&2
    exit "${UNREACHABLE}"
  fi
done

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
# The wait has to outlast the build ahead of it. The old bound was 120 polls x 2s = 240s
# against a build that takes ~885s, so ANY push made during a build was guaranteed to fail.
QUEUE_WAIT="${PIPS_JENKINS_QUEUE_WAIT:-1800}"
BUILD_URL=""
QUEUE_WHY=""
QUEUE_DEADLINE=$(( SECONDS + QUEUE_WAIT ))
while [ "${SECONDS}" -lt "${QUEUE_DEADLINE}" ]; do
  # `|| true`: a transport blip mid-poll is not a verdict. The loop retries; only running out
  # of patience is conclusive, and that is reported as "did not run" rather than as red.
  ITEM="$(curl -fsS "${AUTH[@]}" "${QUEUE_URL}api/json" 2>/dev/null || true)"
  BUILD_URL="$(printf '%s' "${ITEM}" | jq -r '.executable.url // empty' 2>/dev/null || true)"
  [ -n "${BUILD_URL}" ] && break
  # Keep the last reason the controller gave. An EMPTY `why` is not evidence of reachability --
  # the item may be gone, or the poll may have failed -- so only a non-empty one may claim it.
  QUEUE_WHY="$(printf '%s' "${ITEM}" | jq -r '.why // empty' 2>/dev/null || true)"
  sleep 2
done
if [ -z "${BUILD_URL}" ]; then
  if [ -n "${QUEUE_WHY}" ]; then
    still_queued "${QUEUE_WHY}"
  fi
  unreachable "the build never left the queue"
fi
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
