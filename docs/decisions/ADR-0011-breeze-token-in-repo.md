# ADR-0011 · Breeze session token lives in the tracked `.env`

**Status:** accepted · **Date:** 2026-08-31 · **Amends:** constitution rule 14, §2.2

## Context
The Breeze session token rotates daily. Under rule 14 all secrets live in VM-side env files
and never in git, which means each day's token has to be placed on arb-vm out-of-band. The
owner wants the token in a git-tracked `.env` instead, on the basis that the repository is
private.

The concern was raised before the decision and is recorded here rather than omitted: **git
history is permanent.** A value committed once remains in every clone and every fork forever,
and rotating the token afterwards does not remove it from past commits. "Private repository"
is a control that can change — a collaborator added later, a compromised laptop, a CI runner
with read access, a fork. The owner weighed this and chose the tracked file.

## Decision
`.env` is **tracked**, and the Breeze data-plane credentials live in it. Three things are
explicitly **not** changed:

1. **The token never enters a container image.** `.dockerignore` excludes `.env`, no
   Dockerfile copies it, and `tests/unit/test_secrets_and_data_locality.py` pins both. A
   token in a private repo is a bounded risk the owner accepted; a token baked into a
   distributed image is a different risk that nobody accepted.
2. **Order-plane credentials stay out.** Rule 7 keeps the two planes in separate processes
   with separate credentials; broker secrets remain in the VM-side env file the order adapter
   reads. This ADR moves the *data* plane's token only.
3. **Market data still lives only on the VM.** Rule 14's data half is untouched, and is now
   also pinned by a test: the repo's `data/` zones must contain nothing but `.gitkeep`.

## Consequences
- Daily rotation is a commit. `ops/runbooks/breeze-token.md` is the procedure.
- Anyone with repo access, now or in future, has the current token. Rotation limits the
  window to one day, which is the main thing making this tolerable.
- The Jenkins controller mounts the repo read-only, so the token is visible inside that
  container. It is loopback-only and single-user, so this changes little in practice — but it
  is a consequence, not an oversight.
- If the repository is ever made public or shared more widely, **rotate the Breeze
  credentials first and treat every historical token as disclosed.**

## Alternatives
- **VM-side env file (the rule-14 default):** nothing in git, and the compose file already
  wires `/srv/pips/secrets/breeze.env`. Rejected by the owner as less convenient for a value
  that changes daily.
- **Encrypted in the repo (sops/age):** git-tracked workflow without plaintext in history.
  Offered and not chosen; it remains the obvious upgrade path if the repository's audience
  ever widens, and adopting it later would not require undoing this ADR — only re-encrypting.
