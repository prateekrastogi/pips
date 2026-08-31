# ADR-0007 · Task runner and CI

**Status:** accepted · **Date:** 2026-08-31 · **Contract:** `[C-DEPLOY-01]`

## Context
The project needs one obvious way to run every command, and one CI that certifies exactly
what production will run. Owner policy: no archived or abandoned tooling under a trading
system.

## Decision
Task entry points are a plain **`Makefile`** (no `just`). CI is **native Jenkins, running
locally** via a root `Jenkinsfile` (no GitHub Actions). Jenkins stages mirror the Make
targets 1:1 and execute **inside the project's own Docker image**, so a green Jenkins build
certifies the same image arb-vm will run. Merging to main requires green Jenkins; main is
what the deploy rail ships.

## Alternatives
- `just`: nicer ergonomics, and an extra dependency with a weaker support guarantee.
- GitHub Actions: moves CI off the machine that owns the data and the static egress IP.

## Consequences
"Works on my machine" is structurally impossible: laptop, Jenkins and VM run the identical
container. Every new target is added to the Makefile *and* the Jenkinsfile ladder.
