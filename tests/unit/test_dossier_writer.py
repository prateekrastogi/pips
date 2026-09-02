"""Drafting a dossier from what the factory actually measured  (§12.2, M20, `[C-WRIT-01]`).

`[C-DOSS-01]` checks a dossier; this writes one, and the two halves fail in opposite directions.
A checker that is too lax certifies unmeasured strategies. A writer that is too *helpful* does
the same thing one step earlier and leaves no trace: a default of `0.0` for a missing PBO, or a
`"none"` for kill thresholds nobody set, produces a dossier that is complete, hashes cleanly,
binds to its bundle and is entirely invented.

So the writer's contract is subtractive. **It fills only what it can derive, and it names
everything it could not.** There is no default anywhere in it.

**The caller cannot hand-write a gate.** Gate measurements come from the candidate's metrics
against thresholds declared here; evidence supplied for a gate path is refused outright.
Otherwise the writer is a way to inject a passing `Measurement`, which is the one thing the
whole `[C-DOSS-01]` / `[C-CERT-01]` chain is built to prevent.

**A metric that did not compute is not a metric.** NaN and infinity are unsupplied, not values.

**The draft's account of the gap must agree with the checker's.** If the writer thinks it filled
a field the checker calls hollow, one of them is wrong and nobody would find out.
"""

from __future__ import annotations

import inspect
import re

import pytest

from pips.certification.dossier import REQUIRED_FIELDS, Measurement, check_completeness
from pips.certification.writer import (
    GATE_SOURCES,
    METRIC_SOURCES,
    DossierDraft,
    MetricSource,
    UndeclaredEvidenceError,
    draft_dossier,
)
from pips.selection.pareto import Candidate

GATE_PATHS = {spec.path for spec in GATE_SOURCES}
DERIVED_PATHS = {spec.path for spec in METRIC_SOURCES}
ALL_PATHS = {f"{s}.{f}" for s, fields in REQUIRED_FIELDS.items() for f in fields}


def metrics(**over: float) -> dict[str, float]:
    base: dict[str, float] = {
        spec.metric: (spec.threshold if spec.threshold is not None else 0.04)
        for spec in METRIC_SOURCES
    }
    base.update(over)
    return base


def evidence_for(paths: set[str]) -> dict[str, object]:
    """Plausible caller-side evidence for every non-gate path asked for."""
    return {path: f"evidence:{path}" for path in sorted(paths)}


def draft(**over: object) -> DossierDraft:
    supplied_metrics = over.pop("metrics", metrics())
    evidence = evidence_for(ALL_PATHS - DERIVED_PATHS)
    evidence.update(over)
    return draft_dossier(
        candidate=Candidate(id="A01", metrics=supplied_metrics),  # type: ignore[arg-type]
        evidence=evidence,
    )


# --------------------------------------------------------------- derive, never default -----


@pytest.mark.parametrize("spec", GATE_SOURCES, ids=lambda s: s.path)
def test_a_supplied_metric_becomes_a_measurement_at_the_declared_threshold(
    spec: MetricSource,
) -> None:
    """Every gate, not just the first — which is `at_least`, so pinning one direction there
    left both `at_most` gates free to be written with the wrong one."""
    result = draft(metrics=metrics(**{spec.metric: 0.99}))
    section, _, field = spec.path.partition(".")
    value = result.dossier.sections[section][field]

    assert isinstance(value, Measurement)
    assert (value.value, value.threshold, value.direction) == (
        0.99,
        spec.threshold,
        spec.direction,
    )


def test_a_missing_metric_is_unsupplied_not_defaulted() -> None:
    """`0.0` for an unmeasured PBO is a perfect score, and it certifies."""
    spec = GATE_SOURCES[0]
    absent = {k: v for k, v in metrics().items() if k != spec.metric}
    result = draft(metrics=absent)

    section, _, field = spec.path.partition(".")
    assert field not in result.dossier.sections.get(section, {})
    assert spec.path in result.unsupplied


@pytest.mark.parametrize("broken", [float("nan"), float("inf"), float("-inf")])
def test_a_metric_that_did_not_compute_is_not_a_metric(broken: float) -> None:
    spec = GATE_SOURCES[0]
    result = draft(metrics=metrics(**{spec.metric: broken}))
    assert spec.path in result.unsupplied


def test_nothing_hollow_is_ever_written() -> None:
    """No `None`, no `""`, no `"TBD"` — the writer has no way to say "I do not know" in a field.

    It says it in `unsupplied` instead, where a reader will see it.
    """
    result = draft(metrics={})
    written = {
        f"{section}.{field}" for section, body in result.dossier.sections.items() for field in body
    }
    report = check_completeness(result.dossier)
    assert not (written & set(report.hollow)), report.hollow


def test_the_draft_agrees_with_the_completeness_check() -> None:
    """If the writer thinks it filled what the checker calls missing, one of them is wrong."""
    result = draft(metrics={"net_return": 0.04})
    report = check_completeness(result.dossier)
    assert set(result.unsupplied) == set(report.missing) | set(report.hollow)


# ------------------------------------------------------------- gates are not for sale -----


@pytest.mark.parametrize("derived_path", sorted(DERIVED_PATHS))
def test_the_caller_cannot_hand_write_a_derived_field(derived_path: str) -> None:
    """A supplied gate injects a passing Measurement; a supplied `net_return` chooses the rank.

    Both are the caller deciding something the measurement was supposed to decide.
    """
    with pytest.raises(UndeclaredEvidenceError, match=re.escape(derived_path)):
        draft(**{derived_path: Measurement(0.99, 0.95, "at_least")})


def test_the_thresholds_are_not_a_parameter() -> None:
    """A caller-supplied bar means the strategy chooses what it must clear."""
    taken = set(inspect.signature(draft_dossier).parameters)
    assert not (taken & {"thresholds", "gates", "gate_sources", "bars"}), taken


def test_an_undeclared_evidence_path_is_refused() -> None:
    """A typo'd path would sit in the dossier while the real field reported missing."""
    with pytest.raises(UndeclaredEvidenceError, match=re.escape("operations.kill_threshold")):
        draft(**{"operations.kill_threshold": "flat at 2%"})


# ------------------------------------------------------------------- what it records -----


def test_the_draft_says_where_each_value_came_from() -> None:
    spec = GATE_SOURCES[0]
    result = draft()
    assert f"{spec.path} <- metric:{spec.metric}" in result.supplied
    assert "operations.kill_thresholds <- evidence" in result.supplied


def test_a_full_evidence_set_drafts_a_complete_dossier() -> None:
    result = draft()
    report = check_completeness(result.dossier)

    assert result.unsupplied == ()
    assert report.complete, (report.missing, report.hollow)


def test_an_empty_candidate_still_drafts_what_the_caller_knows() -> None:
    """Partial is the expected output, not an error: the gap is the finding."""
    result = draft(metrics={})
    assert result.dossier.sections["operations"]["kill_thresholds"]
    assert set(result.unsupplied) == DERIVED_PATHS


# ---------------------------------------------------------- the gap, pinned in a test -----


def test_only_concentration_still_has_no_declared_threshold() -> None:
    """Pinned deliberately, so closing the gap has to touch a test that says it existed.

    ADR-0014 resolved five of the original six from the reference material. Concentration is the
    one that could not be: its numbers (>30% of PnL from <5% of days, >40% from one name) appear
    only under §11.4 *Tripwires — auto-flags in every report*, and the certification table gives
    it no number at all. Promoting a monitoring flag to a hard gate is a stronger claim than the
    source makes, so it stays a decision.
    """
    from pips.certification.certify import HARD_GATES

    assert set(HARD_GATES) > GATE_PATHS
    assert sorted(set(HARD_GATES) - GATE_PATHS) == ["stability.concentration"]


@pytest.mark.parametrize("boolean", [True, False])
def test_a_boolean_metric_is_not_a_measurement(boolean: bool) -> None:
    """`True` is an `int`, so it would be written as a DSR of 1.0 — a perfect deflated Sharpe
    from a flag. `float()` accepts it silently, so the refusal has to be explicit."""
    spec = GATE_SOURCES[0]
    result = draft(metrics={**metrics(), spec.metric: boolean})
    assert spec.path in result.unsupplied


def test_a_supplied_gate_and_a_supplied_ranking_are_refused_for_different_reasons() -> None:
    """Both are the caller deciding what a measurement should have decided, but the harm
    differs: one injects a passing Measurement, the other picks the rank. A reader who hits
    either needs to be told which one they hit.
    """
    with pytest.raises(UndeclaredEvidenceError, match="passing Measurement"):
        draft(**{"stability.pbo": Measurement(0.01, 0.25, "at_most")})

    with pytest.raises(UndeclaredEvidenceError, match="caller-chosen ranking"):
        draft(**{"economics.net_return": 9.99})


def test_every_threshold_matches_the_gates_ledger() -> None:
    """The ledger is where a bar is read from; the code only applies it.

    `gates.yaml` says a threshold change means editing that file, the enforcing code and an ADR
    in one commit. Nothing checked the "and the enforcing code" half, so the two could drift and
    the ledger would go on describing a bar nobody applies — which is worse than no ledger,
    because it reads as evidence.
    """
    from pathlib import Path

    from pips.ledger.model import load_ledger

    ledger = load_ledger(Path(__file__).resolve().parents[2] / "docs" / "ledger")
    declared = {
        row.threshold["path"]: (row.threshold["value"], row.threshold["direction"])
        for row in ledger.gates
        if "path" in row.threshold
    }
    in_code = {spec.path: (spec.threshold, spec.direction) for spec in GATE_SOURCES}

    assert in_code == declared


def test_the_disclosed_fields_have_no_ledger_row() -> None:
    """A row would be a bar, and the blueprint discloses these rather than gating them."""
    from pathlib import Path

    from pips.certification.certify import DISCLOSED
    from pips.ledger.model import load_ledger

    ledger = load_ledger(Path(__file__).resolve().parents[2] / "docs" / "ledger")
    declared = {row.threshold.get("path") for row in ledger.gates}

    assert not (set(DISCLOSED) & declared)


# ------------------------------------------- a Measurement is a claim about a threshold -----


def test_a_measurement_for_an_undeclared_gate_is_refused() -> None:
    """The hole this rule closes, and it was in the worst possible place.

    `stability.concentration` is the one hard gate ADR-0014 deliberately left without a bar.
    Because the writer did not derive it, it fell through to ordinary caller evidence — so a
    caller could hand-write `Measurement(0.99, threshold=999.0, "at_most")` and clear the very
    gate the ADR says nobody has agreed on. Every other gate was protected; the undecided one
    was not.
    """
    with pytest.raises(UndeclaredEvidenceError, match="no declared threshold"):
        draft(**{"stability.concentration": Measurement(0.99, 999.0, "at_most")})


def test_a_measurement_for_a_disclosed_field_is_refused() -> None:
    """The blueprint discloses the 2x results rather than gating them (ADR-0014), so a bar here
    is invented too.

    The refusal moved as the disclosures became DERIVED metrics: a caller can no longer supply
    them at all, Measurement or not, which is stronger than refusing only the bar. The "no
    declared threshold" branch still covers fields that are neither derived nor gated —
    `stability.concentration` above.
    """
    with pytest.raises(UndeclaredEvidenceError, match="derived from the measured metric"):
        draft(**{"stress.cost_2x": Measurement(0.2, 0.0, "at_least")})

    with pytest.raises(UndeclaredEvidenceError, match="derived from the measured metric"):
        draft(**{"stress.cost_2x": 0.2})


@pytest.mark.parametrize(
    "path", ["operations.kill_thresholds", "capacity.positions", "identity.strategy_id"]
)
def test_a_measurement_anywhere_undeclared_is_refused(path: str) -> None:
    """One rule rather than a list: a `Measurement` may appear only where a bar is declared.

    Stated generally so a field added later is covered without anyone remembering — which is
    exactly how `stability.concentration` slipped through in the first place.
    """
    with pytest.raises(UndeclaredEvidenceError, match="no declared threshold"):
        draft(**{path: Measurement(1.0, 0.0, "at_least")})


def test_a_plain_value_for_an_undeclared_gate_is_still_recorded() -> None:
    """The measurement exists independently of the bar, and refusing it would lose it.

    Recorded as a bare number, it is honestly *ungated*: `[C-CERT-01]` refuses to certify on it
    and says so. That is the true state — measured, not gateable — and it is not the same as
    unmeasured.
    """
    result = draft(**{"stability.concentration": 0.28})
    assert result.dossier.sections["stability"]["concentration"] == 0.28


def test_a_non_numeric_value_is_carried_when_no_bar_applies() -> None:
    """`stability.bootstrap_ci` is an INTERVAL, and the writer refused it as "did not compute".

    `_usable` exists to reject NaN, infinity and booleans — a metric that did not compute is not
    a metric. But that reasoning is about NUMBERS, and it was being applied to every value: a
    two-element interval failed the finiteness check and reached the dossier as unsupplied while
    the registry held it.

    A threshold can only be applied to a number, so a source WITH one still demands one.
    """
    result = draft(metrics={**metrics(), "bootstrap_ci": [-3.5, -2.0]})
    assert result.dossier.sections["stability"]["bootstrap_ci"] == [-3.5, -2.0]
    assert "stability.bootstrap_ci" not in result.unsupplied


@pytest.mark.parametrize("broken", [float("nan"), float("inf"), True, None])
def test_a_gate_still_demands_a_finite_number(broken: object) -> None:
    """The rule narrowed, it did not go away: a bar cannot be applied to a non-number."""
    spec = GATE_SOURCES[0]
    result = draft(metrics={**metrics(), spec.metric: broken})
    assert spec.path in result.unsupplied


@pytest.mark.parametrize("hollow", [None, "", ()])
def test_a_hollow_plain_value_is_still_unsupplied(hollow: object) -> None:
    """Widening what counts as a value must not make emptiness count as one."""
    result = draft(metrics={**metrics(), "bootstrap_ci": hollow})
    assert "stability.bootstrap_ci" in result.unsupplied
