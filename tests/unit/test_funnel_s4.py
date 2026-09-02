"""The S4 deflated-Sharpe gate  `[G-S4-DSR]` (§3.6, M18).

The last `planned` row before the active milestone, and the reason `economics.dsr` shows up in
`certify-smoke` as a field the factory cannot supply: nothing computes it.

**The gate is applied at N = M, not at N = M_erank.** Understating the trial count *raises* the
DSR, and `M_erank ≤ M` always, so gating on the effective count is the flattering direction.
Both ends are reported — §3.6 asks for the bracket — but only the conservative one decides.

**N is every viewed trial, not the number of candidates being gated.** A gate that deflates by
"how many am I looking at right now" instead of "how many were ever looked at" understates N by
whatever the funnel already discarded, which is most of them. That is rule 4 made operational,
and it is the difference between a real correction and a decorative one.

**A candidate that cannot be scored is named and refused**, never silently dropped and never
admitted. A series too short to estimate a Sharpe is not evidence of a good one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from pips.search.funnel import DSR_MIN, gate_s4
from pips.search.registry import Registry, RunRecord

if TYPE_CHECKING:
    from pathlib import Path


def record(**over: Any) -> RunRecord:
    base: dict[str, Any] = {
        "config_hash": "a" * 64,
        "stage": "S4",
        "stage_rank": 5,
        "family": "A01",
        "universe_id": "FIXTURES",
        "session_mask": "ALL",
        "capital_tier": "2L",
        "broker": "FLATTRADE",
        "data_snapshot": "fixtures@f",
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


def seeded(mean: float, n: int = 120, *, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(mean, 0.01, n)


def with_returns(registry: Registry, tmp_path: Path, series: np.ndarray, **over: Any) -> int:
    run_id = registry.record(record(**over))
    path = registry.write_daily_returns(tmp_path / f"{run_id}.parquet", series)
    registry.record(record(**{**over, "daily_returns_ref": str(path)}))
    return run_id


def build(tmp_path: Path, means: list[float], **over: Any) -> Registry:
    registry = Registry(tmp_path / "registry.db")
    for index, mean in enumerate(means):
        series = seeded(mean, seed=7 + index)
        path = registry.write_daily_returns(tmp_path / f"r{index}.parquet", series)
        registry.record(
            record(
                config_hash=f"{index:064x}",
                daily_returns_ref=str(path),
                **over,
            )
        )
    return registry


# ------------------------------------------------------------------- the bracket -----


def test_both_ends_of_the_bracket_are_reported(tmp_path: Path) -> None:
    """§3.6 asks for `(M_erank, M)`, because a single number hides which N produced it."""
    report = gate_s4(build(tmp_path, [0.004, 0.001, 0.0005]), stage="S4")

    assert report.trials_literal == 3
    assert report.trials_effective is not None
    scored = report.admitted + report.rejected
    assert all(b.dsr_at_literal is not None for b in scored)
    assert all(b.dsr_at_effective is not None for b in scored)


def test_the_effective_count_never_exceeds_the_literal(tmp_path: Path) -> None:
    report = gate_s4(build(tmp_path, [0.004, 0.001, 0.0005]), stage="S4")
    assert report.trials_effective is not None
    assert report.trials_effective <= report.trials_literal


def test_the_verdict_uses_the_literal_count(tmp_path: Path) -> None:
    """Deflating by the smaller N raises every DSR, so the effective count must not decide.

    `dsr_at_effective >= dsr_at_literal` for every candidate — if the gate ever read the
    effective one it would admit strictly more, which is the flattering direction.
    """
    report = gate_s4(build(tmp_path, [0.004, 0.001, 0.0005]), stage="S4")
    for bracket in report.admitted + report.rejected:
        assert bracket.dsr_at_effective >= bracket.dsr_at_literal
        assert bracket.passes == (bracket.dsr_at_literal >= DSR_MIN)


# --------------------------------------------------------------- N is every trial -----


def test_the_trial_count_includes_rows_that_are_not_being_gated(tmp_path: Path) -> None:
    """Rule 4 made operational: N is every trial ever viewed, not the survivors in front of us.

    Counting only the candidates being gated understates N by whatever the funnel already
    discarded — which is most of them — and understating N raises the DSR.
    """
    registry = build(tmp_path, [0.004, 0.001])
    for index in range(20):
        registry.record(record(config_hash=f"{index + 100:064x}", status="viewed"))

    report = gate_s4(registry, stage="S4")
    assert report.trials_literal == 22
    assert len(report.admitted) + len(report.rejected) == 2


def test_more_trials_never_raise_the_dsr(tmp_path: Path) -> None:
    """Looking at more things cannot make one of them more believable."""
    small = gate_s4(build(tmp_path / "a", [0.004, 0.001]), stage="S4")

    registry = build(tmp_path / "b", [0.004, 0.001])
    for index in range(50):
        registry.record(record(config_hash=f"{index + 100:064x}", status="viewed"))
    large = gate_s4(registry, stage="S4")

    by_id = {b.run_id: b for b in large.admitted + large.rejected}
    for bracket in small.admitted + small.rejected:
        assert by_id[bracket.run_id].dsr_at_literal <= bracket.dsr_at_literal


# ------------------------------------------------------ unscorable is not admitted -----


def test_a_candidate_with_no_returns_is_named_not_dropped(tmp_path: Path) -> None:
    registry = build(tmp_path, [0.004])
    registry.record(record(config_hash="f" * 64, stage="S4", stage_rank=5))

    report = gate_s4(registry, stage="S4")
    assert any("no daily returns" in note for note in report.excluded)
    assert len(report.admitted) + len(report.rejected) == 1


def test_a_series_too_short_to_score_is_excluded_not_passed(tmp_path: Path) -> None:
    """A series too short to estimate a Sharpe is not evidence of a good one."""
    registry = Registry(tmp_path / "registry.db")
    path = registry.write_daily_returns(tmp_path / "short.parquet", np.array([0.01]))
    registry.record(record(config_hash="a" * 64, daily_returns_ref=str(path)))

    report = gate_s4(registry, stage="S4")
    assert report.admitted == ()
    assert report.rejected == ()
    assert len(report.excluded) == 1


def test_only_the_named_stage_is_gated(tmp_path: Path) -> None:
    registry = build(tmp_path, [0.004, 0.001])
    other = build(tmp_path / "other", [0.004], stage="S1", stage_rank=1)
    assert other is not registry

    report = gate_s4(registry, stage="S1")
    assert report.admitted == ()
    assert report.rejected == ()


# ------------------------------------------------------------------ determinism -----


def test_the_report_is_stable_across_runs(tmp_path: Path) -> None:
    registry = build(tmp_path, [0.004, 0.001, 0.0005])
    first, second = gate_s4(registry, stage="S4"), gate_s4(registry, stage="S4")
    assert first == second


def test_the_threshold_matches_the_gates_ledger() -> None:
    """`gates.yaml` is where a bar is read from; this only applies it."""
    from pathlib import Path

    from pips.ledger.model import load_ledger

    ledger = load_ledger(Path(__file__).resolve().parents[2] / "docs" / "ledger")
    row = next(r for r in ledger.gates if r.id == "G-S4-DSR")
    assert row.threshold["dsr_min"] == DSR_MIN


def test_a_candidate_that_only_passes_at_the_effective_count_is_rejected(tmp_path: Path) -> None:
    """The property the whole gate turns on, and the one the assertions above only imply.

    With many viewed trials, `M` is large and `M_erank` is small — so there is a Sharpe that
    clears 0.95 when deflated by the effective count and fails when deflated by the literal one.
    A gate reading the effective end would admit it. This one must not.
    """
    # Tuned by probe, not by guess: at these means candidate 3 scores 0.874 at N = M and 0.958
    # at N = M_erank, straddling the 0.95 bar. 403 trials viewed against an effective rank of
    # 2.99 — because only three runs preserved returns — which is the understatement at its
    # most extreme and exactly why the literal end has to decide.
    registry = build(tmp_path, [0.0025, 0.002, 0.0015])
    for index in range(400):
        registry.record(record(config_hash=f"{index + 1000:064x}", status="viewed"))

    report = gate_s4(registry, stage="S4")
    assert report.trials_effective is not None
    assert report.trials_effective < report.trials_literal

    flattered = [b for b in report.rejected if b.dsr_at_effective >= DSR_MIN > b.dsr_at_literal]
    assert flattered, (
        "no candidate distinguishes the two ends, so this fixture proves nothing about which "
        "one the gate reads",
        [(b.run_id, b.dsr_at_literal, b.dsr_at_effective) for b in report.rejected],
    )
    assert all(b not in report.admitted for b in flattered)


def test_a_short_series_that_is_not_flat_is_still_excluded(tmp_path: Path) -> None:
    """Separated from the flat case on purpose.

    A one-element series is BOTH too short and (trivially) flat, so a single fixture lets each
    guard hide behind the other: delete either and the test still passes. Two observations with
    real variation exercise the length guard alone.
    """
    registry = Registry(tmp_path / "registry.db")
    path = registry.write_daily_returns(tmp_path / "short.parquet", np.array([0.01, -0.02]))
    registry.record(record(config_hash="a" * 64, daily_returns_ref=str(path)))

    report = gate_s4(registry, stage="S4")
    assert report.admitted == () and report.rejected == ()
    assert "fewer than" in report.excluded[0]


def test_a_flat_series_long_enough_to_score_is_still_excluded(tmp_path: Path) -> None:
    """And the other half: long enough, but a Sharpe divided by zero is not a Sharpe."""
    registry = Registry(tmp_path / "registry.db")
    path = registry.write_daily_returns(tmp_path / "flat.parquet", np.full(60, 0.001))
    registry.record(record(config_hash="a" * 64, daily_returns_ref=str(path)))

    report = gate_s4(registry, stage="S4")
    assert report.admitted == () and report.rejected == ()
    assert "flat" in report.excluded[0]


def test_a_viewed_trial_counts_toward_n_but_is_not_gated(tmp_path: Path) -> None:
    """Rule 4's two halves pull in opposite directions and both must hold.

    A trial that was looked at COUNTS toward the multiplicity — that is the whole point — but it
    was not completed, so it is not a candidate. Scoring it would let an abandoned run be
    admitted; not counting it would understate N and raise everyone's DSR.
    """
    registry = build(tmp_path, [0.004])
    series = seeded(0.01, seed=99)
    path = registry.write_daily_returns(tmp_path / "viewed.parquet", series)
    registry.record(record(config_hash="e" * 64, daily_returns_ref=str(path), status="viewed"))

    report = gate_s4(registry, stage="S4")
    scored = {b.run_id for b in report.admitted + report.rejected}
    assert len(scored) == 1
    assert report.trials_literal == 2, "the viewed trial must still count toward N"


def test_candidates_are_reported_in_numeric_run_order(tmp_path: Path) -> None:
    """Eleven of them, because sorting ids as STRINGS puts 10 before 2 — deterministic, and
    unreadable. A report nobody can scan is a report nobody checks."""
    registry = build(tmp_path, [0.004] * 11)
    report = gate_s4(registry, stage="S4")

    ids = [int(b.run_id) for b in report.admitted + report.rejected]
    assert ids == sorted(ids)
    assert len(ids) == 11
