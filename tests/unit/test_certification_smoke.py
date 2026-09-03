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

from typing import TYPE_CHECKING, Any

import pytest

from pips.certification.dossier import REQUIRED_FIELDS, is_hollow

if TYPE_CHECKING:
    from pathlib import Path

from pips.certification.smoke import (
    KNOWN_FIELDS,
    REGISTRY_FIELDS,
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
    del incomplete["cost_model"]
    with pytest.raises(KeyError) as exc:
        evidence_from_run(incomplete, code_version="a" * 40)
    assert "snapshot_root" in str(exc.value)
    assert "cost_model" in str(exc.value)


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
        "trials_viewed",
        "multiplicity_effective",
    }


# ------------------------------------------- what the REGISTRY knows about this candidate -----


def _record(**over: Any) -> Any:
    from pips.search.registry import RunRecord

    base: dict[str, Any] = {
        "config_hash": "a" * 64,
        "stage": "S1",
        "stage_rank": 1,
        "family": "A03",
        "universe_id": "NIFTY100",
        "session_mask": "MID",
        "capital_tier": "5L",
        "broker": "FLATTRADE",
        "data_snapshot": "silver@2026H1",
        "snapshot_root": "b" * 64,
        "cost_model": "c" * 64,
        "fill_tier": "F1",
        "seed": 0,
        "git_sha": "0" * 40,
        "metrics": {"rank_ic": 0.1},
        "status": "completed",
    }
    base.update(over)
    return RunRecord(**base)


def test_the_registry_supplies_what_it_recorded_about_this_run(tmp_path: Path) -> None:
    """These four were reported as "the factory cannot supply" while the registry held them.

    Every one is `[C-NOM-01]`'s argument applied a layer down: a number the search already
    recorded must not be re-typed by a human, because re-typing is how a dossier comes to
    describe a slightly different run than the one that happened.
    """
    from pips.certification.smoke import evidence_from_registry
    from pips.search.registry import Registry

    registry = Registry(tmp_path / "registry.db")
    run_id = registry.record(_record())

    evidence = evidence_from_registry(registry, str(run_id))
    assert evidence["identity.family_graph"] == "A03"
    assert evidence["trade_context.universe_policy"] == "NIFTY100"
    assert evidence["trade_context.session_regime"] == "MID"
    assert evidence["trade_context.capital_range"] == "5L"


def test_the_parents_are_the_earlier_runs_of_the_same_config(tmp_path: Path) -> None:
    """A promotion is a NEW row for the same config at a higher stage, so its parents are the
    earlier rows carrying that config hash — not a guess, and not the whole registry."""
    from pips.certification.smoke import evidence_from_registry
    from pips.search.registry import Registry

    registry = Registry(tmp_path / "registry.db")
    parent = registry.record(_record(stage="S1", stage_rank=1))
    registry.record(_record(config_hash="d" * 64, stage="S1", stage_rank=1))
    promoted = registry.record(_record(stage="S5", stage_rank=6))

    evidence = evidence_from_registry(registry, str(promoted))
    assert evidence["identity.parent_experiment_ids"] == str(parent)


def test_a_run_the_registry_does_not_have_is_refused(tmp_path: Path) -> None:
    """A candidate with no row is a candidate nobody can trace."""
    from pips.certification.smoke import evidence_from_registry
    from pips.search.registry import Registry

    with pytest.raises(LookupError, match="404"):
        evidence_from_registry(Registry(tmp_path / "registry.db"), "404")


def test_a_run_with_no_parents_says_so_rather_than_leaving_it_empty(tmp_path: Path) -> None:
    """An empty tuple is HOLLOW by the dossier's own rule, and would report "this run has no
    parents" as "nobody recorded the parents" — the conflation the whole subsystem refuses.

    So the value is always a string: the ids, or an explicit statement that there are none.
    """
    from pips.certification.dossier import is_hollow
    from pips.certification.smoke import evidence_from_registry
    from pips.search.registry import Registry

    registry = Registry(tmp_path / "registry.db")
    only = registry.record(_record())

    value = evidence_from_registry(registry, str(only))["identity.parent_experiment_ids"]
    assert not is_hollow(value)
    assert "none" in value
    assert str(only) not in value, "a row that names itself as its own parent is not a lineage"


def test_the_two_evidence_sources_are_disjoint() -> None:
    """A field in both would be supplied twice, and a merge silently prefers one.

    They are not interchangeable: the run report is per-RUN, the registry row is per-CANDIDATE.
    `broker` and `capital_range` were briefly in both, and the per-candidate one is the truthful
    answer whenever a search spans more than one venue or tier.
    """
    assert not (set(KNOWN_FIELDS) & set(REGISTRY_FIELDS))


def test_a_same_stage_sibling_is_not_a_parent(tmp_path: Path) -> None:
    """The rank comparison is STRICT, and that is what keeps a run out of its own lineage.

    Two rows for one config at the same stage are alternatives, not ancestors — and if `<`
    became `<=` they would each become the other's parent, and every run its own.
    """
    from pips.certification.smoke import evidence_from_registry
    from pips.search.registry import Registry

    registry = Registry(tmp_path / "registry.db")
    sibling = registry.record(_record(stage="S5", stage_rank=6))
    promoted = registry.record(_record(stage="S5", stage_rank=6))

    value = evidence_from_registry(registry, str(promoted))["identity.parent_experiment_ids"]
    assert str(sibling) not in value
    assert str(promoted) not in value


# --------------------------------------------------------- found by mutation sweep ---


def test_the_data_version_carries_the_snapshot_root_not_just_its_name() -> None:
    """A name labels a snapshot; the root identifies it.

    `[C-DATA-02]` pins results to Merkle roots precisely so a run can be re-derived from the
    bytes it actually read. `identity.data_version` recording only `august-panel` says which
    snapshot somebody meant and not which one they got — and the two diverge exactly when it
    matters, after a snapshot is rebuilt or corrected under the same name.
    """
    evidence = evidence_from_run(
        {
            "snapshot_name": "august-panel",
            "snapshot_root": "a" * 64,
            "cost_model": "nse_equity_intraday@v1",
            "trials_viewed": 120,
            "multiplicity_effective": 7.5,
        },
        code_version="abc1234",
    )

    assert evidence["identity.data_version"] == f"august-panel@{'a' * 64}"


def test_the_gap_report_reads_the_same_however_it_was_assembled() -> None:
    """Sorted, so two runs of one cycle produce a diffable report.

    The output is read by a human comparing one cycle against the next, and a listing whose
    order follows whichever nominee happened to be processed first turns "nothing changed" into
    a diff full of moved lines. Input order is not a property of the cycle.
    """
    forwards = format_gap({"A01": ("x.y",), "B02": ("p.q",)}, certified=0)
    backwards = format_gap({"B02": ("p.q",), "A01": ("x.y",)}, certified=0)

    assert forwards == backwards
    assert forwards[0] == "certify-smoke: 0 certified"
    assert forwards[1].startswith("  A01:")
