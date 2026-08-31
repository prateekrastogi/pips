# ADR-0008 · Unblock protocol

**Status:** accepted · **Date:** 2026-08-31

## Context
An autonomous loop that grinds on a blocked item burns context and produces nothing. Most
real blocks sit at a boundary the working session cannot see well: Jenkins, compose,
arb-vm, the deploy rail, broker onboarding.

## Decision
When a milestone's Verify still fails after ~3 distinct attempts, or the failure sits at
such a boundary, the session **stops**, writes `docs/state/blocks/BLK-####.md`, and spawns
a **fresh** agent whose role is synthesized for that blocker's domain — never a generic
helper. The specialist gets the role, the block card and the constitution pointer; not the
milestone context and not the doc layer (fresh context is the point). It appends root
cause, the change made, verification output and a **prevention artifact** to the card.

## Alternatives
- Keep trying in-session: the failure mode this ADR exists to stop.
- One standing "ops helper" agent: accumulates the same stale context it should escape.

## Consequences
Block cards are never deleted — they are the outage history. A recurring domain (a third
Jenkins block) triggers redesign, not a third rescue. Human-only blocks flip to
`escalated: human` and surface in `CURRENT.md` until answered.
