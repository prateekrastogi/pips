"""Driving a certification cycle end to end  (§3.6/§12, M20, `[C-RUN-01]`).

Every piece existed; the thing that did not was the ORDER, and the order is the whole design.

**The holdout confirms; it never selects.** Finalists are chosen on development evidence, and
only then is the lockbox opened — once, for all of them together. A candidate that was not a
finalist can never be certified, however well the holdout would have treated it. Promoting one
after the fact is selection on the holdout, and reaching for a second look to check would void
the cycle outright (§3.6: one unlock; twice = void).

**One look, many candidates.** The sin is looking twice, not measuring several things in one
look, so the single unlock evaluates the whole finalist set.

**An empty field never opens the box.** If nothing survives development, the sealed window stays
sealed — there is nothing to confirm, and an unlock recorded against no result is a look nobody
can account for.

**Signing happens after the holdout, not before.** The bundle must commit to a dossier that
already contains the holdout result, or the signature covers evidence that was still to come.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import pytest

from pips.bundle import IrNode, verify_bundle
from pips.certification.certify import MAX_CERTIFIED
from pips.certification.dossier import (
    REQUIRED_FIELDS,
    Dossier,
    Measurement,
    bind_dossier,
    build_dossier,
)
from pips.certification.run import (
    CertificationRun,
    HoldoutResultError,
    Nominee,
    run_certification,
)
from pips.data.lockbox import SealedLockbox
from pips.search.registry import Registry

if TYPE_CHECKING:
    from pathlib import Path

KEY = b"test-signing-key"
START, END = date(2026, 7, 1), date(2026, 8, 1)
ALPHA = (IrNode(op="zscore", inputs=("close",), params={"window": 20}),)
PORTFOLIO = (IrNode(op="erc_weights", inputs=("alpha",), params={}),)

PASSING_GATES: dict[str, Measurement] = {
    "economics.dsr": Measurement(0.97, 0.95, "at_least"),
    "stability.pbo": Measurement(0.18, 0.25, "at_most"),
    "stability.spa_p": Measurement(0.04, 0.10, "at_most"),
    "stability.parameter_plateau": Measurement(0.80, 0.70, "at_least"),
    "stability.concentration": Measurement(0.30, 0.40, "at_most"),
    "stress.cost_1_5x": Measurement(0.60, 0.00, "at_least"),
    "stress.delay_1_bar": Measurement(0.55, 0.00, "at_least"),
    "stability.outer_folds": Measurement(24, 12, "at_least"),
}


def pre_holdout_dossier(**over: object) -> Dossier:
    """Everything a development run can know. `stability.lockbox_result` is absent by design."""
    sections: dict[str, dict[str, Any]] = {
        name: {field: f"{name}.{field}" for field in fields}
        for name, fields in REQUIRED_FIELDS.items()
    }
    del sections["stability"]["lockbox_result"]
    for path, measurement in PASSING_GATES.items():
        section, _, field = path.partition(".")
        sections[section][field] = measurement
    sections["economics"]["net_return"] = over.pop("net_return", 0.04)
    sections["stress"]["cost_2x"] = 0.20
    sections["stress"]["delay_2_bar"] = 0.10
    for path, value in over.items():
        section, _, field = path.partition(".")
        sections[section][field] = value
    return build_dossier(sections)


def provenance_for(strategy_id: str) -> dict[str, Any]:
    from pips.certification.bundle_writer import HASH_FIELDS, REQUIRED_PROVENANCE

    base: dict[str, Any] = {}
    for index, name in enumerate(sorted(REQUIRED_PROVENANCE)):
        base[name] = f"{index:064x}" if name in HASH_FIELDS else f"{strategy_id}-{name}"
    base["strategy_id"] = strategy_id
    base["golden_fixture_hashes"] = ("a" * 64,)
    base["parent_experiment_ids"] = ("exp-1",)
    base["valid_from"] = "2026-09-01"
    base["valid_until"] = "2026-12-01"
    return base


def nominee(strategy_id: str, **over: object) -> Nominee:
    """`net_return` rides in `over` rather than as its own parameter: the other keys are dotted
    paths and it is not one, and a typed parameter beside `**object` makes every `**{path: ...}`
    call site a possible target for it."""
    return Nominee(
        strategy_id=strategy_id,
        dossier=pre_holdout_dossier(**over),
        provenance=provenance_for(strategy_id),
        alpha_ir=ALPHA,
        portfolio_ir=PORTFOLIO,
    )


class Holdout:
    """Records what it was asked to measure, and how often."""

    def __init__(self, results: dict[str, float] | None = None) -> None:
        self.results = results
        self.favours: dict[str, float] = {}
        self.calls: list[tuple[date, date, tuple[str, ...]]] = []

    def __call__(self, start: date, end: date, finalists: tuple[str, ...]) -> dict[str, float]:
        self.calls.append((start, end, finalists))
        if self.results is not None:
            return self.results
        # Only ever answers about whom it was asked. `favours` says what it WOULD say about
        # anyone, which is the point of the non-finalist test: it is never consulted for them.
        return {name: self.favours.get(name, 0.5) for name in finalists}


def seal() -> SealedLockbox:
    return SealedLockbox(start=START, end=END, release_stage="S6", cycle_id="cycle-1")


def run(
    nominees: list[Nominee], tmp_path: Path, holdout: Holdout | None = None
) -> CertificationRun:
    return run_certification(
        nominees=nominees,
        registry=Registry(tmp_path / "registry.db"),
        lockbox=seal(),
        stage="S6",
        evaluate_holdout=holdout or Holdout(),
        key=KEY,
    )


# ------------------------------------------------- the holdout confirms, never selects -----


def test_the_holdout_is_opened_once_for_all_finalists_together(tmp_path: Path) -> None:
    holdout = Holdout()
    result = run([nominee(f"A{i:02d}", net_return=0.01 * i) for i in (1, 2, 3)], tmp_path, holdout)

    assert len(holdout.calls) == 1
    start, end, finalists = holdout.calls[0]
    assert (start, end) == (START, END)
    assert set(finalists) == {"A01", "A02", "A03"}
    assert result.lockbox is not None


def test_a_non_finalist_is_never_certified_however_the_holdout_treats_it(
    tmp_path: Path,
) -> None:
    """The sharpest property here. A candidate that failed development is not resurrected by a
    holdout it was never entered into — and asking the box a second time to check would void
    the cycle.
    """
    nominees = [
        nominee("GOOD", net_return=0.04),
        nominee("BAD", net_return=0.99, **{"stability.pbo": Measurement(0.9, 0.25, "at_most")}),
    ]
    # An evaluation that WOULD rate BAD far above GOOD, if it were ever asked about it. It is
    # not: the finalist list is settled before the box opens, and a result for a non-finalist is
    # refused outright — so the property holds more strongly than "BAD is not certified".
    holdout = Holdout()
    holdout.favours = {"GOOD": 0.5, "BAD": 99.0}

    result = run(nominees, tmp_path, holdout)

    assert "BAD" not in holdout.calls[0][2], "a failed candidate was entered into the holdout"
    assert [c.strategy_id for c in result.certification.certified] == ["GOOD"]
    assert any(r.strategy_id == "BAD" for r in result.not_finalists)


def test_an_empty_field_never_opens_the_box(tmp_path: Path) -> None:
    """An unlock recorded against no result is a look nobody can account for."""
    registry = Registry(tmp_path / "registry.db")
    holdout = Holdout()
    result = run_certification(
        nominees=[nominee("A01", **{"stability.pbo": Measurement(0.9, 0.25, "at_most")})],
        registry=registry,
        lockbox=seal(),
        stage="S6",
        evaluate_holdout=holdout,
        key=KEY,
    )

    assert holdout.calls == []
    assert result.lockbox is None
    assert registry.holdout_unlock_count("cycle-1") == 0
    assert result.certification.certified == ()


def test_the_best_five_get_the_look_and_the_rest_are_named(tmp_path: Path) -> None:
    """Which five, not just how many.

    Asserting the count alone lets the sort run backwards unnoticed — and the single holdout
    look would then be spent on the five WORST candidates. And the three that miss out have to
    be named: dropping them silently reports a field of five where eight were considered.
    """
    holdout = Holdout()
    result = run(
        [nominee(f"A{i:02d}", net_return=0.01 * i) for i in range(1, 9)], tmp_path, holdout
    )

    assert len(holdout.calls[0][2]) == MAX_CERTIFIED
    assert set(holdout.calls[0][2]) == {"A08", "A07", "A06", "A05", "A04"}
    assert result.finalists == ("A08", "A07", "A06", "A05", "A04")

    out_ranked = {r.strategy_id: r.reasons for r in result.not_finalists}
    assert set(out_ranked) == {"A01", "A02", "A03"}
    assert all("ranked below" in " | ".join(reasons) for reasons in out_ranked.values())


# ------------------------------------------------------- signing follows the holdout -----


def test_the_signed_bundle_commits_to_the_holdout_result(tmp_path: Path) -> None:
    """Signing first would cover evidence that was still to come."""
    result = run([nominee("A01")], tmp_path)
    certified = result.certification.certified[0]

    verify_bundle(certified.bundle, key=KEY)
    bind_dossier(certified.dossier, certified.bundle)
    assert certified.dossier.sections["stability"]["lockbox_result"] is not None


# ------------------------------------------------------------ the holdout must answer -----


def test_a_finalist_missing_from_the_holdout_result_is_refused(tmp_path: Path) -> None:
    """The box was opened and somebody was not measured — a broken evaluation, not a failing
    candidate, and the difference matters because the unlock is already spent."""
    holdout = Holdout({"A01": 0.5})
    with pytest.raises(HoldoutResultError, match="A02"):
        run([nominee("A01"), nominee("A02")], tmp_path, holdout)


def test_an_unexpected_id_in_the_holdout_result_is_refused(tmp_path: Path) -> None:
    """Something that was not a finalist was measured against the sealed window."""
    holdout = Holdout({"A01": 0.5, "STOWAWAY": 0.9})
    with pytest.raises(HoldoutResultError, match="STOWAWAY"):
        run([nominee("A01")], tmp_path, holdout)


# -------------------------------------------------------------------- honest outputs -----


def test_a_nominee_that_fails_a_gate_is_named_not_dropped(tmp_path: Path) -> None:
    result = run(
        [nominee("A01", **{"stability.spa_p": Measurement(0.9, 0.1, "at_most")})], tmp_path
    )
    reasons = " | ".join(result.not_finalists[0].reasons)
    assert result.not_finalists[0].strategy_id == "A01"
    assert "stability.spa_p" in reasons


def test_an_unsignable_nominee_is_reported_not_dropped(tmp_path: Path) -> None:
    bad = Nominee(
        strategy_id="A01",
        dossier=pre_holdout_dossier(),
        provenance={**provenance_for("A01"), "code_hash": "not-a-hash"},
        alpha_ir=ALPHA,
        portfolio_ir=PORTFOLIO,
    )
    result = run([bad], tmp_path)

    assert result.certification.certified == ()
    assert result.unsignable[0].strategy_id == "A01"
    assert "code_hash" in " | ".join(result.unsignable[0].reasons)


def test_no_nominees_at_all_is_not_an_error(tmp_path: Path) -> None:
    result = run([], tmp_path)
    assert result.certification.certified == ()
    assert result.lockbox is None


def test_a_second_run_on_the_same_cycle_voids_it(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "registry.db")
    for _ in range(1):
        run_certification(
            nominees=[nominee("A01")],
            registry=registry,
            lockbox=seal(),
            stage="S6",
            evaluate_holdout=Holdout(),
            key=KEY,
        )
    with pytest.raises(RuntimeError, match="VOID"):
        run_certification(
            nominees=[nominee("A01")],
            registry=registry,
            lockbox=seal(),
            stage="S6",
            evaluate_holdout=Holdout(),
            key=KEY,
        )


def test_the_same_nominees_choose_the_same_finalists(tmp_path: Path) -> None:
    """Two runs of one cycle must not disagree about who got the look."""
    forward = run(
        [nominee("A01", net_return=0.04), nominee("A02", net_return=0.04)],
        tmp_path / "a",
        Holdout(),
    )
    backward = run(
        [nominee("A02", net_return=0.04), nominee("A01", net_return=0.04)],
        tmp_path / "b",
        Holdout(),
    )
    assert forward.finalists == backward.finalists


# ---------------------------------------------------- the state of the factory today -----


def test_a_dossier_from_the_writer_cannot_reach_the_holdout_yet(tmp_path: Path) -> None:
    """The honest end-to-end result while `stability.concentration` has no bar (ADR-0014).

    Nothing is certified, the box is never opened, and the report names the reason — which is a
    finding, not a failure. Inventing the bar to make this test green is the one thing the whole
    `[C-WRIT-01]` design refuses.
    """
    from pips.certification.writer import METRIC_SOURCES, draft_dossier
    from pips.selection.pareto import Candidate

    # Every DERIVED path excluded, enumerated from METRIC_SOURCES rather than listed: adding
    # gross_to_net and cost_share left a hand-written exclusion list silently short.
    derived = {spec.path for spec in METRIC_SOURCES}
    evidence = {
        f"{s}.{f}": f"{s}.{f}"
        for s, fields in REQUIRED_FIELDS.items()
        for f in fields
        if f"{s}.{f}" not in derived
    }
    del evidence["stability.lockbox_result"]
    metrics = {
        spec.metric: (0.0 if spec.direction == "at_most" else 1.0) if spec.threshold else 0.04
        for spec in METRIC_SOURCES
    }
    draft = draft_dossier(candidate=Candidate(id="A01", metrics=metrics), evidence=evidence)

    holdout = Holdout()
    result = run_certification(
        nominees=[
            Nominee(
                strategy_id="A01",
                dossier=draft.dossier,
                provenance=provenance_for("A01"),
                alpha_ir=ALPHA,
                portfolio_ir=PORTFOLIO,
            )
        ],
        registry=Registry(tmp_path / "registry.db"),
        lockbox=seal(),
        stage="S6",
        evaluate_holdout=holdout,
        key=KEY,
    )

    assert result.certification.certified == ()
    assert holdout.calls == []
    assert "stability.concentration" in " | ".join(result.not_finalists[0].reasons)


def test_provenance_naming_a_different_strategy_is_refused(tmp_path: Path) -> None:
    """`Nominee.strategy_id` and `bundle.strategy_id` are two names for one thing, and nothing
    but this ties them. If they disagree, the run reports finalists under one id and certifies
    under another, and no audit can match them up.

    Refused rather than overwritten: silently correcting the provenance hides a caller whose
    bundle is built from the wrong config.
    """
    mismatched = Nominee(
        strategy_id="A01",
        dossier=pre_holdout_dossier(),
        provenance={**provenance_for("A01"), "strategy_id": "A99"},
        alpha_ir=ALPHA,
        portfolio_ir=PORTFOLIO,
    )
    result = run([mismatched], tmp_path)

    assert result.certification.certified == ()
    assert "A99" in " | ".join(result.not_finalists[0].reasons)
