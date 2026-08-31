"""Experiment manifest [C-REG-01] (§6 M11, reference Appendix B).

A manifest is a **pre-registration**: what will be searched, on what data, under which
protocol, with which seed — written down *before* the search, so the trial that lands in the
registry can be checked against what was declared rather than against what turned out well.

The status field is the load-bearing part. `PROPOSED` is a claim about the future; anything
else is a claim about the past, and the two must not be confused after the fact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pips.search.manifest import Experiment, ManifestStatus, load_manifest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "config" / "search_spaces" / "example_manifest.yaml"


def test_the_appendix_b_example_parses() -> None:
    m = load_manifest(EXAMPLE)
    assert m.experiment.alpha.id == "A04"
    assert m.experiment.seed == 1407
    assert m.experiment.status is ManifestStatus.PROPOSED


def test_every_appendix_b_field_is_represented() -> None:
    # If the reference's manifest carries a field this model drops, the pre-registration is
    # weaker than the document claims — and the gap would be invisible.
    declared = {
        "protocol",
        "alpha",
        "data",
        "universe",
        "session",
        "broker_context",
        "capital_inr",
        "costs",
        "validation",
        "seed",
        "status",
    }
    assert declared <= set(Experiment.model_fields)


def test_the_manifest_is_content_addressed() -> None:
    # The manifest hash is what ties a pre-registration to the trials it produced.
    a = load_manifest(EXAMPLE)
    assert len(a.content_hash()) == 64
    assert a.content_hash() == load_manifest(EXAMPLE).content_hash()


def test_changing_any_parameter_changes_the_hash() -> None:
    base = load_manifest(EXAMPLE)
    changed = base.model_copy(
        update={"experiment": base.experiment.model_copy(update={"seed": base.experiment.seed + 1})}
    )
    assert changed.content_hash() != base.content_hash()


def test_a_stress_grid_must_include_the_unstressed_case() -> None:
    # Reporting only stressed numbers hides the baseline; reporting only the baseline is the
    # error M16 exists to prevent. The grid must contain 1.0 and at least one value above it.
    with pytest.raises(ValueError, match=r"1\.0"):
        load_manifest(EXAMPLE).experiment.costs.model_copy(
            update={"stress": [1.5, 2.0]}
        ).validate_grid()


def test_an_unknown_session_is_refused() -> None:
    m = load_manifest(EXAMPLE)
    with pytest.raises(ValueError, match="session"):
        m.experiment.model_copy(update={"session": "LUNCHTIME"}).validate_session()


def test_a_non_tradeable_session_cannot_be_pre_registered() -> None:
    # CAS is disabled as an alpha venue (ADR-0004); FLATTEN_ONLY is exposure-reducing only.
    # Pre-registering a search on either would propose an experiment we may not run.
    m = load_manifest(EXAMPLE)
    for session in ("CAS", "FLATTEN_ONLY"):
        with pytest.raises(ValueError, match="not a tradeable session"):
            m.experiment.model_copy(update={"session": session}).validate_session()
