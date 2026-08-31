# ADR-0009 · Test-first (TDD) is a constitution rule

**Status:** accepted · **Date:** 2026-08-31 · **Gate:** `[G-TDD-01]`

## Context
Rule 10 already said "tests are the deliverable", but said nothing about *order*. Tests
written after the code are shaped by the code: they encode what was built rather than what
was required, and they very often cannot fail. In a system whose entire claim is that its
evidence chain is trustworthy, a test that was never observed to fail is decoration — the
same category the constitution rejects for mathematics.

## Decision
Test-first becomes **constitution rule 16** with an operational protocol (§7.1): red →
green → refactor, with the red output recorded in the session log and PR body. Enforcement
is mechanical: `make tdd-check` walks the branch oldest-first and fails any commit that
adds production code (`python/pips/`, `rust/crates/`, `schemas/`, `apps/`) without a test
in that commit or an earlier one. It runs inside `make ci`, so Jenkins refuses the branch.

The single bypass is a `TDD-Exempt: <reason>` commit trailer for pure renames and
mechanical refactors whose behaviour is already pinned. It is printed by CI on every run —
loud by construction. An empty reason is not an exemption.

## Alternatives
- Prose-only rule: unenforceable, and this project's whole thesis is that prose without a
  machine check drifts. Rejected.
- Require a separate red commit then a green commit: cleanest evidence, but noisy history
  and easy to fake by amending. The ordering check plus recorded red output gets most of
  the value at a fraction of the friction.
- Coverage threshold instead: measures lines touched, not whether a test could ever fail.

## Consequences
The checker sees **ordering**; only the recorded red output proves the test could fail.
Both are required, and faking either is the same offence as weakening a golden (rule 10).
M0 itself is the rule's first application: `tests/unit/test_tdd.py` was written, run red,
and only then did `python/pips/ledger/tdd.py` exist.
