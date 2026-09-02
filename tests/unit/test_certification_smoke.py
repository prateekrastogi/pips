"""M20's Verify, made runnable: how far the factory is from certifying anything `[C-SMOKE-01]`.

Every other milestone's *Verify* has a Make target — `s1-smoke`, `s5-smoke`, `backtest-smoke`.
M20's did not, so "the chain works and is blocked on one threshold" was a claim in a log rather
than something anyone could run.

The honest difficulty is that a certification dossier wants things the factory does not produce:
kill thresholds, flatten deadlines, minimum economic ticket. The tempting smoke run fills those
with `"smoke"` and reports a certified bundle, which would be a lie with a signature on it.

So this supplies **only what the run genuinely knows** — the git sha it was built from, the
snapshot root it read, the trial counts the registry recorded, the cluster S5 computed — and
reports everything else as unsupplied. The output is a map of what is actually missing, which is
the useful artifact while the answer is zero.
"""

from __future__ import annotations

from typing import Any

import pytest

from pips.certification.dossier import REQUIRED_FIELDS, is_hollow
from pips.certification.smoke import (
    KNOWN_FIELDS,
    RUN_FIELDS,
    evidence_from_run,
    format_gap,
)

ALL_PATHS = {f"{s}.{f}" for s, fields in REQUIRED_FIELDS.items() for f in fields}


def run_report(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "snapshot_root": "b" * 64,
        "snapshot_name": "fixtures@fixtures",
        "trials_viewed": 812,
        "multiplicity_literal": 812,
        "multiplicity_effective": 41.5,
        "cost_model": "flattrade-2026H2",
        "broker": "FLATTRADE",
        "capital_tier": "2L",
    }
    base.update(over)
    return base


# ------------------------------------------------------------- only what it knows -----


def test_the_evidence_carries_nothing_hollow() -> None:
    """A `"smoke"` in `operations.kill_thresholds` is a lie that a signature would then cover."""
    evidence = evidence_from_run(run_report(), code_version="a" * 40)
    hollow = {path for path, value in evidence.items() if is_hollow(value)}
    assert hollow == set()


def test_the_evidence_supplies_only_declared_known_fields() -> None:
    """`KNOWN_FIELDS` is the claim: these, and no others, come from a real run."""
    evidence = evidence_from_run(run_report(), code_version="a" * 40)
    assert set(evidence) == set(KNOWN_FIELDS)
    assert set(KNOWN_FIELDS) < ALL_PATHS


def test_the_real_numbers_are_the_registrys_not_invented() -> None:
    """`trials_viewed` and `m_erank` are rule 4's numbers — the two a dossier cannot fake."""
    evidence = evidence_from_run(
        run_report(trials_viewed=99, multiplicity_effective=7.5), code_version="a" * 40
    )
    assert evidence["stability.trials_viewed"] == 99
    assert evidence["stability.m_erank"] == 7.5


@pytest.mark.parametrize("field", RUN_FIELDS)
def test_a_missing_run_field_is_refused_not_defaulted(field: str) -> None:
    """A run report that lost its snapshot root cannot describe what it read.

    Parametrised over every key, because a check covering five of seven refuses some gaps and
    lets the rest through as a bare `KeyError` from the dict access — which reads the same to a
    machine and tells a person nothing.
    """
    incomplete = run_report()
    del incomplete[field]
    with pytest.raises(KeyError, match=field):
        evidence_from_run(incomplete, code_version="a" * 40)


def test_all_the_gaps_are_named_at_once() -> None:
    """Otherwise a caller with three gaps learns them one run at a time."""
    incomplete = run_report()
    del incomplete["snapshot_root"]
    del incomplete["broker"]
    with pytest.raises(KeyError) as exc:
        evidence_from_run(incomplete, code_version="a" * 40)
    assert "snapshot_root" in str(exc.value)
    assert "broker" in str(exc.value)


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_an_unknown_code_version_is_refused_including_whitespace(blank: str) -> None:
    """Whitespace is the version that looks filled in."""
    with pytest.raises(ValueError, match="code_version"):
        evidence_from_run(run_report(), code_version=blank)


def test_an_unknown_code_version_is_refused() -> None:
    """A dossier whose `code_version` is a guess cannot be checked against the repository."""
    with pytest.raises(ValueError, match="code_version"):
        evidence_from_run(run_report(), code_version="")


def test_the_evidence_never_names_a_gate() -> None:
    """Gates are derived from measured metrics; supplying one is refused by `[C-WRIT-01]`,
    and this must not be the caller that trips it."""
    from pips.certification.writer import METRIC_SOURCES

    derived = {spec.path for spec in METRIC_SOURCES}
    assert not (set(KNOWN_FIELDS) & derived)


def test_the_evidence_never_names_the_correlation_cluster() -> None:
    """S5's to state (`[C-NOM-01]`)."""
    assert "decision.correlation_cluster" not in KNOWN_FIELDS


# ------------------------------------------------------------------- the report -----


def test_the_gap_report_names_every_unsupplied_field() -> None:
    lines = format_gap({"A01": ("operations.kill_thresholds", "capacity.positions")}, certified=0)
    text = "\n".join(lines)
    assert "operations.kill_thresholds" in text
    assert "capacity.positions" in text


def test_the_gap_report_says_zero_rather_than_nothing() -> None:
    """A report that prints only the gaps reads as a warning; the count is the verdict."""
    text = "\n".join(format_gap({"A01": ()}, certified=0))
    assert "0 certified" in text


def test_the_gap_report_counts_the_fields_not_just_lists_them() -> None:
    """Twenty-six missing fields and two are different situations, and a list buries that."""
    gaps = {"A01": tuple(sorted(ALL_PATHS - set(KNOWN_FIELDS)))}
    text = "\n".join(format_gap(gaps, certified=0))
    assert str(len(gaps["A01"])) in text


def test_run_fields_names_every_key_the_evidence_reads() -> None:
    """Pinned as a literal, not read back from the module.

    The parametrised test above takes its cases FROM `RUN_FIELDS`, so shrinking the tuple
    shrinks the test with it and both go green — a self-referential check that verifies only
    its own consistency. This is the independent statement of what the function reads.
    """
    assert set(RUN_FIELDS) == {
        "snapshot_name",
        "snapshot_root",
        "cost_model",
        "broker",
        "capital_tier",
        "trials_viewed",
        "multiplicity_effective",
    }
