# ADR-0002 · Kernel strategy: one implementation, in Rust

**Status:** accepted · **Date:** 2026-08-31 · **Contract:** `[C-PAR-01]`

## Context
Anything that ships inside a signed bundle must compute identically in research and in
production. Two independent implementations of an EWMA drift apart at the ULP level, and
then at the decision level.

## Decision
Every bundle-crossing primitive — rolling/stateful ops, bar building, robust z, EWMA,
residualizers, calibration application, band logic — is implemented **once, in the Rust
`math-kernel` crate**, exposed to Python through a narrow PyO3 binding (`math-python`). A
deliberately slow pure-Python oracle exists **only** for property tests. Research-only
statistics (DSR/PBO/SPA, bootstraps, reporting) stay in Python.

## Alternatives
- NumPy in research, Rust in production: the parity problem this ADR exists to prevent.
- Everything in Python: cannot meet the execution plant's latency and safety bar.

## Consequences
Release parity replays recorded days through both paths; canonical OrderIntent JSONL must
be byte-equal (`sha256(py) == sha256(rs)`). The binding is a build dependency of the
research image, which is why the research container carries a Rust toolchain.
