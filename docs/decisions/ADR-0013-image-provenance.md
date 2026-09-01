# ADR-0013 — the verify image must prove which commit it holds

**Status:** accepted · 2026-09-01
**Supersedes nothing. Related:** ADR-0009 (test-first), §2 rule 10 (never weaken a gate).

## Context

`docker compose run research make ci` — the command CLAUDE.md named as THE way to verify —
printed `ci: green` from `pips/research:current`, an image built 2026-08-31 from commit
`4d4916f`. Its `python/pips/validation/` package held four modules; HEAD's held twenty. It ran
511 tests. HEAD had 1049. Nothing in the output distinguished that from a real green.

The compose service resolves `image: pips/research:${PIPS_SHA:-current}` with no bind mount and
no build on run, so with `PIPS_SHA` unset — every laptop invocation — it runs a floating tag
that nothing on that machine keeps current.

This had already happened once, on arb-vm, and was patched there: `ops/deploy/sync.sh:204`
republishes `:current` after every successful deploy, with the comment *"observed live: an
hour-old build from before the invoked command existed"*. That patch works, and it is a
**per-machine maintenance obligation**: every machine that resolves the floating tag must
remember to refresh it. The laptop never did, so the same defect regrew on the other machine.

## Decision

**The image states which commit it was built from; the caller states which commit it believes
it is testing; and the ladder runs only if those agree.** `make provenance` is the first
dependency of `make ci`, and Jenkins asserts it as its own stage immediately after the build.

Three states, not two:

- **on the host** — the working tree IS the thing under test, nothing can be stale, no check.
  A stray `PIPS_EXPECTED_SHA` in someone's shell must not start failing host runs.
- **in an image that names its commit** — compared against the expectation; mismatch refuses.
- **in an image that cannot name its commit** — refused, and deliberately NOT treated as a host
  run. Collapsing this into the host case would reopen the entire hole the first time someone
  forgets `--build-arg PIPS_SHA=`.

An absent expectation is a refusal, not a pass. That is exactly how the stale image produced
its green: there was no expectation for it to contradict. Because compose writes
`${PIPS_EXPECTED_SHA:-}`, the empty string is normalised to unset, so two absences cannot agree
with each other and report a match.

`make ci-container` is the documented verify. It builds the image from the working tree and
passes the commit it built, so the good path cannot produce a stale image and the check is not
something a person has to remember.

## Consequences

- A green now names its commit, and says `working tree DIRTY at build time` when it is. A dirty
  tree does not refuse: verifying uncommitted work is the point of the local loop, and Jenkins
  answers the pushed-SHA question separately.
- The floating `${PIPS_SHA:-current}` default is LEFT IN PLACE. Making it mandatory
  (`${PIPS_SHA:?...}`) would fail every compose invocation that does not set it — including
  status and health commands on the deploy rail, whose blast radius reaches trading-path
  services. The provenance check defends at the point of use instead, which needs no
  cooperation from the tag.
- Any image built at or after this commit refuses rather than lies, including through the old
  command: compose supplies no expectation, so it is refused. Images built BEFORE this commit
  have no preflight; the laptop's stale `pips/research:current` was deleted rather than left as
  a live landmine, and arb-vm's is replaced by `sync.sh` on the next deploy.
- `sync.sh`'s republish is now belt-and-braces rather than the only defence. It is kept: it
  costs nothing and keeps a manual VM invocation on recent code.
