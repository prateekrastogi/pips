# ADR-0004 · Session taxonomy

**Status:** accepted · **Date:** 2026-08-31 · **Contract:** `[C-SESS-01]`

## Context
v1's open/mid/close split is too coarse: the 09:15–09:30 shock and the post-14:30 window
behave nothing like mid-session, and the closing auction is a different venue entirely.

## Decision
Six states: `OPEN_SHOCK` 09:15–09:30 · `OPEN_DIGEST` 09:30–10:30 · `MID` 10:30–14:30 ·
`LATE_CTS` 14:30→broker cutoff · `CAS` 15:15–15:35 · `FLATTEN_ONLY`. **CAS is disabled as
an alpha venue** until auction data and broker support are verified. Session eligibility is
broker × product × instrument × side, read from the daily capability snapshot — never a
hard-coded time.

## Alternatives
- Keep three states: hides the diurnal structure the alphas trade. Rejected.
- Enable CAS now: no auction data, no F3 fills, no broker confirmation. Rejected.

## Consequences
Square-off times are *data*. A broker changing its cutoff is a snapshot change, not a code
change.
