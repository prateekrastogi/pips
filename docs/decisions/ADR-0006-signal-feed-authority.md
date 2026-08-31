# ADR-0006 · Signal-feed authority

**Status:** accepted · **Date:** 2026-08-31 · **Gate:** `[G-AUTH-0]`

## Context
ICICI's public FAQ restricts Breeze to personal trading and prohibits third-party trading
integration. It supports self-built code but publishes no explicit data-only carve-out for
signals executed at another broker. The architecture uses Breeze purely as a read-only data
plane, which is plausibly fine and not documented as fine.

## Decision
Breeze remains the research/data plane through P0–P5. **Before any live order**, either
written ICICI clarification is obtained, or the certified signal feed swaps to the
execution broker's entitled feed (Kite Connect live+historical tier, or Flattrade's API
subject to its terms). This is a release gate and an adapter swap, not an architecture
change. Breeze data is never redistributed.

## Alternatives
- Assume it is permitted: an unbounded legal risk on the live path. Rejected.
- Swap to the broker feed now: pays for and rebuilds against a feed we may not need. Deferred.

## Consequences
`G-AUTH-0` blocks the live flag chain. The data plane is written behind an adapter seam so
the swap is a config change, and M3 files the question from `ops/runbooks/authority.md`.
