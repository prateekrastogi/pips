# ADR-0005 · Alpha registry

**Status:** accepted · **Date:** 2026-08-31 · **Contract:** `[C-SPEC-01]`

## Context
Two reference documents describe the same alpha families under different names (v1's
F1–F10 and the AlphaForge A01–A36 catalogue). One of them has to be canonical or the
registry accumulates duplicate trials under different labels.

## Decision
The **A-catalogue (A01–A36)** is canonical. v1's F-ids are retained as aliases per the §5
mapping. Tiering governs admission: T1 (A01–A18, A27, A29, A30) is the launch surface on
1-minute bars with F1 fills; T2 waits for the quote/trade/depth archive; T3 waits for
event/auction entitlements.

## Alternatives
- Keep both namespaces live: guarantees double-counted trials in the multiplicity ledger.

## Consequences
Every alpha enters as an AlphaSpec with predeclared falsifiers. An F-id in a config
resolves to its A-id before a trial is recorded.
