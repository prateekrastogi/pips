# ADR-0014 · Hard-gate thresholds, and which "gates" are disclosures

**Status:** accepted · **Date:** 2026-09-02 · **Affects:** `[C-CERT-01]`, `[C-WRIT-01]`, P4

## Context
`[C-CERT-01]` enforces nine hard gates named in P4. Writing `[C-WRIT-01]` showed that only
three of them had a number anywhere — DSR 0.95, PBO 0.25, SPA 0.10, and of those only `dsr_min`
was in `gates.yaml`; the other two lived in P4 prose. The remaining six were named without a
bar in prose, ledger or code, so no drafted dossier could ever pass certification.

The tempting fix is to pick six plausible numbers. That is exactly the failure `[C-WRIT-01]`
exists to refuse: an invented threshold produces a dossier that is complete, hashes cleanly,
binds to its bundle, and certifies against a bar nobody agreed to.

So the reference material was consulted by section instead, and it resolves five of the six.

## Decision

**Three are gates with cited bars.**

| Gate | Bar | Source |
|---|---|---|
| `stability.parameter_plateau` | median perturbed net SR ≥ **0.70 × centre** | Meta-Algorithm Blueprint §S3 robustness battery: *"median perturbed net SR ≥ 70% of center"* |
| `stress.cost_1_5x` | net return ≥ **0** at 1.5× cost | Indian Blueprint certification table: *"Positive after 1.5× cost"* |
| `stress.delay_1_bar` | net return ≥ **0** at +1 bar | same row: *"survives +1-bar delay"* |

**Two are not gates at all.** The same certification row reads *"…; 2× result **disclosed**"*.
`stress.cost_2x` and `stress.delay_2_bar` are **disclosures**: required to be present, never
held to a bar. They are removed from `HARD_GATES` and named in `DISCLOSED`.

This is a correction, not a relaxation. Gating them would reject strategies the specification
certifies — a defect even though it errs strict — and it would misreport what the blueprint
asks for. A `Measurement` placed in a disclosed field is now refused, because a threshold there
is one somebody invented.

**One remains a decision.** `stability.concentration` has no number in any certification
context. The figures that exist — *">30% of annual PnL from <5% of days, or >40% from one
name"* — appear under §11.4 **Tripwires (auto-flags in every report)**, and the certification
table says only *"No single stock/day/session/regime dominates net P&L."* Promoting a monitoring
flag to a hard certification gate is a stronger claim than the source makes, and the two live at
different points in the lifecycle: a tripwire fires on a running strategy, a gate refuses one
that has never traded. It stays open, pinned by a test, until the owner sets it.

Recorded in passing: the blueprint calls the DSR bar *"illustratively ≥95%"*. This project has
already fixed it at 0.95 in `G-S4-DSR`; that is not reopened here.

## Consequences
- `gates.yaml` gains rows for all five, plus the PBO and SPA bars that existed only in prose —
  the ledger, not P4's paragraph, is now where a threshold is read from.
- A test asserts the writer's thresholds equal the ledger's, so the two cannot drift silently.
- The writer drafts six of the seven hard gates. One open decision, not six.
- Certification still cannot run end to end: `stability.concentration` blocks it, deliberately.
