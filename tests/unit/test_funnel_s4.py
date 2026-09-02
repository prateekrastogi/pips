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

from decimal import Decimal
from typing import TYPE_CHECKING, Any

import numpy as np
import pytest

from pips.search.funnel import DSR_MIN, gate_s4
from pips.search.registry import Registry, RunRecord

if TYPE_CHECKING:
    from pathlib import Path


_BAR = 60_000_000_000
_DAY = 86_400_000_000_000
# 2026-01-01 09:15 IST as ns since epoch, near enough: the only thing that matters is that
# STAMPS_2DAY straddles an IST midnight and STAMPS_4 does not.
_OPEN = 1_767_237_300_000_000_000
STAMPS_4 = [_OPEN + i * _BAR for i in range(4)]
STAMPS_20 = [_OPEN + i * _BAR for i in range(20)]
STAMPS_60 = [_OPEN + i * _BAR for i in range(60)]
STAMPS_2DAY = [_OPEN, _OPEN + _BAR, _OPEN + _DAY, _OPEN + _DAY + _BAR]


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
    # ONE HUNDRED, not sixty. `np.std` of a constant array is exactly 0.0 at length 60 and
    # 2.2e-19 at length 100, so a sixty-bar fixture passed this test while the guard it was
    # meant to prove was written as `== 0.0` and would have let the hundred-bar case through --
    # dividing by the noise for a Sharpe around 4.6e15.
    path = registry.write_daily_returns(tmp_path / "flat.parquet", np.full(100, 0.001))
    registry.record(record(config_hash="a" * 64, daily_returns_ref=str(path)))

    report = gate_s4(registry, stage="S4")
    assert report.admitted == () and report.rejected == ()
    # The WHOLE phrase. `"flat" in ...` matched the kurtosis message downstream, because
    # "inflates" contains "flat" -- so the test passed while the guard it was written for was
    # bypassed and something else caught the series by luck.
    assert "the return series is flat" in report.excluded[0], report.excluded


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


# ------------------------------------ per-candidate SPA evidence `[G-S4-DSR]` neighbours -----


def test_every_scorable_candidate_gets_an_adjusted_p(tmp_path: Path) -> None:
    """`stability.spa_p` is per-candidate, so the family-wise `spa_test` p-value cannot fill it
    (see the Romano-Wolf log entry). These are the stepdown's per-hypothesis values."""
    from pips.search.funnel import spa_adjusted_p

    registry = build(tmp_path, [0.004, 0.001, 0.0005])
    result = spa_adjusted_p(registry, stage="S4")

    assert len(result.adjusted_p) == 3
    assert all(0.0 <= p <= 1.0 for p in result.adjusted_p.values())
    assert result.excluded == ()


def test_a_stronger_candidate_gets_no_worse_a_p(tmp_path: Path) -> None:
    from pips.search.funnel import spa_adjusted_p

    registry = build(tmp_path, [0.004, 0.0005])
    result = spa_adjusted_p(registry, stage="S4")

    ids = sorted(result.adjusted_p, key=int)
    assert result.adjusted_p[ids[0]] <= result.adjusted_p[ids[1]]


def test_series_of_different_lengths_are_refused_not_truncated(tmp_path: Path) -> None:
    """Truncating aligns at index 0, which is only correct if every run started the same day.

    The registry's own `daily_returns_matrix` truncates; doing that here would compare a
    strategy's first 40 days against another's first 40 and call the result a p-value.
    """
    from pips.search.funnel import spa_adjusted_p

    registry = build(tmp_path, [0.004])
    short = registry.write_daily_returns(tmp_path / "short.parquet", seeded(0.001, n=60))
    registry.record(record(config_hash="f" * 64, daily_returns_ref=str(short)))

    # Matched on THIS module's reason, not on the word "length": `romano_wolf` refuses unequal
    # lengths too, so a generic match is satisfied by the downstream check and says nothing
    # about the guard here — which is the one that explains why truncating is wrong.
    with pytest.raises(ValueError, match="only correct if every run started on the same day"):
        spa_adjusted_p(registry, stage="S4")


def test_a_candidate_with_no_returns_is_named_in_the_spa_report(tmp_path: Path) -> None:
    """Renamed after mypy caught it shadowing the DSR gate's test of the same name — a
    duplicate `def` silently replaces the earlier one, so that test had stopped running."""
    from pips.search.funnel import spa_adjusted_p

    registry = build(tmp_path, [0.004, 0.001])
    registry.record(record(config_hash="f" * 64, stage="S4", stage_rank=5))

    result = spa_adjusted_p(registry, stage="S4")
    assert len(result.adjusted_p) == 2
    assert any("no daily returns" in note for note in result.excluded)


def test_no_scorable_candidates_is_not_an_error(tmp_path: Path) -> None:
    """An empty family is not a family that passed; `romano_wolf` refuses one, and this must
    not turn that refusal into a crash mid-search."""
    from pips.search.funnel import spa_adjusted_p

    registry = Registry(tmp_path / "registry.db")
    registry.record(record(config_hash="f" * 64))

    result = spa_adjusted_p(registry, stage="S4")
    assert result.adjusted_p == {}
    assert len(result.excluded) == 1


def test_the_p_values_are_reproducible(tmp_path: Path) -> None:
    from pips.search.funnel import spa_adjusted_p

    registry = build(tmp_path, [0.004, 0.001, 0.0005])
    assert spa_adjusted_p(registry, stage="S4") == spa_adjusted_p(registry, stage="S4")


def test_only_completed_runs_at_the_stage_are_scored(tmp_path: Path) -> None:
    """A viewed trial counts toward multiplicity but is not a candidate — the same two halves
    of rule 4 the DSR gate holds apart."""
    from pips.search.funnel import spa_adjusted_p

    registry = build(tmp_path, [0.004])
    path = registry.write_daily_returns(tmp_path / "viewed.parquet", seeded(0.01, seed=99))
    registry.record(record(config_hash="e" * 64, daily_returns_ref=str(path), status="viewed"))

    result = spa_adjusted_p(registry, stage="S4")
    assert len(result.adjusted_p) == 1


# ---------------------------------- the winner's neighbourhood, at full fidelity -----


def test_the_plateau_evaluates_the_winners_two_neighbours() -> None:
    """Successive halving eliminates most configs at low budget, so its surface has gaps
    exactly where the plateau matters — around the winner. The perturbations are evaluated
    fresh, at the winner's own fidelity, which is what the S3 battery actually describes.
    """
    from pips.search.funnel import plateau_for_winner

    grid = ("a", "b", "c", "d", "e")
    seen: list[str] = []

    def score(config: str) -> Decimal:
        seen.append(config)
        return {
            "a": Decimal("9"),
            "b": Decimal("0.6"),
            "c": Decimal("1.0"),
            "d": Decimal("0.8"),
            "e": Decimal("9"),
        }[config]

    ratio = plateau_for_winner(winner="c", candidates=grid, score=score)

    assert ratio == Decimal("0.7")
    assert sorted(seen) == ["b", "c", "d"], "only the winner and its two neighbours"


def test_a_winner_at_the_grid_edge_has_no_plateau() -> None:
    """One-sided evidence is not a plateau.

    An optimum at the boundary of the PRE-REGISTERED domain is the case where the honest answer
    is "we cannot tell" — the surface continues outside the range nobody registered. `None`
    reaches the dossier as unsupplied, and `[C-CERT-01]` then refuses to certify on it.
    """
    from pips.search.funnel import plateau_for_winner

    grid = ("a", "b", "c")
    scores = {"a": Decimal("1.0"), "b": Decimal("0.9"), "c": Decimal("0.8")}

    assert plateau_for_winner(winner="a", candidates=grid, score=scores.__getitem__) is None


def test_a_winner_not_on_the_grid_is_refused() -> None:
    """A winner the grid does not contain has no neighbours to perturb toward."""
    from pips.search.funnel import plateau_for_winner

    with pytest.raises(ValueError, match="not on the grid"):
        plateau_for_winner(winner="z", candidates=("a", "b", "c"), score=lambda _: Decimal(1))


def test_a_two_point_grid_cannot_show_a_plateau() -> None:
    """Both points are edges. A search that registered two values registered no surface."""
    from pips.search.funnel import plateau_for_winner

    scores = {"a": Decimal("1.0"), "b": Decimal("0.9")}
    assert plateau_for_winner(winner="a", candidates=("a", "b"), score=scores.__getitem__) is None


def test_the_bad_neighbour_still_counts() -> None:
    """Same rule as `plateau_ratio`: the perturbation that went badly is the evidence."""
    from pips.search.funnel import plateau_for_winner

    grid = ("a", "b", "c")
    scores = {"a": Decimal("0.1"), "b": Decimal("1.0"), "c": Decimal("0.9")}
    ratio = plateau_for_winner(winner="b", candidates=grid, score=scores.__getitem__)

    assert ratio == Decimal("0.5"), "median of 0.1 and 0.9, not 0.9 alone"


# ---------------------------------------------------- PBO over the grid `[G-P4-PBO]` -----


def test_pbo_needs_more_than_one_config() -> None:
    """`None`, never 0.0.

    A PBO of zero reads as "the in-sample winner never failed out of sample", which is the
    strongest possible statement this gate can make. A single config is both the best and the
    median, so the statistic is undefined — and undefined must not print as perfect.
    """
    from pips.search.funnel import pbo_for_configs

    assert pbo_for_configs({"only": [0.01] * 200}) is None
    assert pbo_for_configs({}) is None


def test_pbo_reports_a_fraction_for_a_real_grid() -> None:
    from pips.search.funnel import pbo_for_configs

    grid = {f"c{i}": [(-1) ** ((t + i) % 3) * 0.01 * (i + 1) for t in range(240)] for i in range(4)}
    result = pbo_for_configs(grid)

    assert result is not None
    assert 0.0 <= result.pbo <= 1.0
    assert result.n_configs == 4


def test_pbo_refuses_series_of_different_lengths() -> None:
    """Delegated to the validator, pinned here: truncating would align at index 0 and compare
    one config's first months against another's."""
    from pips.search.funnel import pbo_for_configs

    with pytest.raises(ValueError, match="length"):
        pbo_for_configs({"a": [0.01] * 200, "b": [0.01] * 100})


def test_pbo_purges_the_forecast_horizon() -> None:
    """The horizon is one bar here — enter at i, exit at i+1 — so a label spans one boundary.

    Not purging it lets the last observation of an in-sample block carry information about the
    first out-of-sample one, which is the leak CSCV's boundary purge exists to close.
    """
    from pips.search.funnel import PBO_HORIZON, pbo_for_configs

    assert PBO_HORIZON == 1

    # Asserting the constant alone proves it is written down, not that it is USED — the same
    # vacuous check that let the pre-push hook's exit code be flattened by make. This observes
    # the purge instead.
    grid = {f"c{i}": [(-1) ** ((t + i) % 3) * 0.01 * (i + 1) for t in range(240)] for i in range(4)}
    result = pbo_for_configs(grid)
    assert result is not None
    assert result.observations_purged > 0, "the boundary purge did not run"


def test_pbo_uses_an_even_number_of_blocks() -> None:
    """CSCV splits S blocks into two halves of S/2; an odd S loses the symmetry it is named
    for, and the validator refuses it."""
    from pips.search.funnel import PBO_BLOCKS

    assert PBO_BLOCKS % 2 == 0


# ------------------------------------------------ §12.2 report-card economics -----


def test_rotation_is_round_trips_per_bar() -> None:
    from pips.search.funnel import report_card_economics

    out = report_card_economics([0.01, -0.02, 0.03, 0.0], [2, 2, 2, 0], STAMPS_4)
    assert out["rotation"] == pytest.approx(1.5)


def test_orders_are_two_per_round_trip() -> None:
    """Entry and exit. The distinction matters: the >=5 orders/s governor counts ORDERS, and
    reporting round trips under a name that says orders would understate it by half."""
    from pips.search.funnel import report_card_economics

    out = report_card_economics([0.01, 0.0, 0.0, 0.0], [3, 0, 0, 0], STAMPS_4)
    assert out["orders_per_day"] == pytest.approx(6.0)


def test_orders_per_day_divides_by_trading_days_not_bars() -> None:
    """Two days of bars must halve the per-day figure, not leave it per-bar."""
    from pips.search.funnel import report_card_economics

    one_day = report_card_economics([0.0] * 4, [1, 1, 1, 1], STAMPS_4)
    two_days = report_card_economics([0.0] * 4, [1, 1, 1, 1], STAMPS_2DAY)
    assert two_days["orders_per_day"] == pytest.approx(one_day["orders_per_day"] / 2)


def test_cvar_is_a_positive_magnitude() -> None:
    """Same sign convention as `max_drawdown`, and stated for the same reason: a negative
    magnitude read as 'larger is better' would rank the worst tail first."""
    from pips.search.funnel import report_card_economics

    out = report_card_economics([-0.10, 0.01, 0.02, 0.03], [1, 1, 1, 1], STAMPS_4)
    assert out["cvar"] > 0


def test_cvar_averages_the_tail_not_just_the_worst() -> None:
    """CVaR is the MEAN beyond the quantile; taking the single worst is VaR's cousin, and on a
    fat tail the two differ by exactly the thing CVaR was chosen to see."""
    from pips.search.funnel import CVAR_LEVEL, report_card_economics

    # SIXTY observations, so the 5% tail is three and averaging is distinguishable from taking
    # the single worst. At twenty the tail rounds to one and the two are the same number — my
    # first fixture proved nothing, and the mutation that replaced the tail with `1` survived.
    losses = [-0.10, -0.08, -0.06] + [0.02] * 57
    out = report_card_economics(losses, [1] * 60, STAMPS_60)
    tail = max(1, round(len(losses) * (1 - CVAR_LEVEL)))

    assert tail == 3, "the fixture must produce a tail wider than one"
    assert out["cvar"] == pytest.approx(0.08)
    assert out["cvar"] != pytest.approx(0.10), "that is the worst observation, not the mean"


def test_a_series_with_no_trades_has_no_rotation() -> None:
    """Zero rotation and zero orders are true, but a series that never traded has no economics
    to report — and 0.0 orders/day would read as a strategy that is cheap to run."""
    from pips.search.funnel import report_card_economics

    out = report_card_economics([0.0] * 4, [0, 0, 0, 0], STAMPS_4)
    assert "rotation" not in out
    assert "orders_per_day" not in out


def test_mismatched_lengths_are_refused() -> None:
    from pips.search.funnel import report_card_economics

    with pytest.raises(ValueError, match="length"):
        report_card_economics([0.01, 0.02], [1, 1, 1], STAMPS_4)


def test_the_bootstrap_ci_is_an_interval_not_a_bound() -> None:
    """The reason the metric channel was widened.

    Recording only the lower bound under the name `bootstrap_ci` would be the `net_return`
    mistake again: a field whose name asserts more than the value holds, in a dossier built to
    be re-checked.
    """
    from pips.search.funnel import bootstrap_sharpe_ci

    trending = [0.01 + 0.001 * ((t * 7) % 5 - 2) for t in range(240)]
    interval = bootstrap_sharpe_ci(trending)

    assert interval is not None
    low, high = interval
    assert low < high


def test_the_ci_brackets_the_sample_sharpe() -> None:
    """A percentile interval from resamples of the series must contain the series' own Sharpe
    except by accident; an interval that does not is measuring something else."""
    from pips.search.funnel import bootstrap_sharpe_ci

    values = [0.01 + 0.001 * ((t * 7) % 5 - 2) for t in range(240)]
    mean = sum(values) / len(values)
    spread = (sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5
    sample = mean / spread

    low, high = bootstrap_sharpe_ci(values)  # type: ignore[misc]
    assert low <= sample <= high


def test_a_flat_series_has_no_ci() -> None:
    """No deviation, no Sharpe, and an interval around a division by zero is not a measurement."""
    from pips.search.funnel import bootstrap_sharpe_ci

    assert bootstrap_sharpe_ci([0.001] * 100) is None


def test_a_series_too_short_has_no_ci() -> None:
    """Two observations WITH variation, so the length rule is what refuses it.

    A single observation is also flat, and the flat check would catch it first — the test would
    then pass with the length guard deleted.
    """
    from pips.search.funnel import bootstrap_sharpe_ci

    assert bootstrap_sharpe_ci([0.01, -0.02]) is None


def test_the_interval_is_narrower_than_the_full_range() -> None:
    """A 95% interval that spans every resample is not a 95% interval.

    `tail = 0` would take the extremes, and every other assertion here still holds of the full
    range: it is an interval, it is ordered, and it brackets the sample.
    """
    from pips.search.funnel import bootstrap_sharpe_ci

    values = [0.01 + 0.004 * ((t * 7) % 11 - 5) for t in range(240)]
    interval = bootstrap_sharpe_ci(values)
    assert interval is not None
    low, high = interval

    from decimal import Decimal

    import numpy as np

    from pips.search.funnel import BLOCK_LENGTH, CI_RESAMPLES, SPA_SEED
    from pips.validation.bootstrap import stationary_bootstrap

    every = sorted(
        float(np.mean(a)) / float(np.std(a))
        for a in (
            np.asarray([float(v) for v in r])
            for r in stationary_bootstrap(
                [Decimal(str(v)) for v in values], CI_RESAMPLES, BLOCK_LENGTH, SPA_SEED
            )
        )
        if a.min() != a.max()
    )
    assert low > every[0], "the lower bound is the minimum resample, so no tail was trimmed"
    assert high < every[-1], "the upper bound is the maximum resample"


def test_the_ci_is_reproducible() -> None:
    from pips.search.funnel import bootstrap_sharpe_ci

    values = [0.01 + 0.001 * ((t * 7) % 5 - 2) for t in range(240)]
    assert bootstrap_sharpe_ci(values) == bootstrap_sharpe_ci(values)


# --------------------------------------- what the search knows about its own trades -----


def test_the_horizon_names_its_unit() -> None:
    """`1.0` in a field called `horizon` does not say bars, minutes or days.

    The metric channel carries strings now, so the honest record is the one a reader cannot
    misread — the same objection as recording a gross return in a field named `net_return`.
    """
    from pips.search.funnel import holding_horizon

    assert holding_horizon(bar_interval_ns=60_000_000_000) == "1 bar (60s)"


def test_the_horizon_reports_the_actual_bar_length() -> None:
    from pips.search.funnel import holding_horizon

    assert holding_horizon(bar_interval_ns=300_000_000_000) == "1 bar (300s)"


def test_a_non_positive_interval_is_refused() -> None:
    """A zero-length bar is not a horizon, and would print as `1 bar (0s)`."""
    from pips.search.funnel import holding_horizon

    with pytest.raises(ValueError, match="interval"):
        holding_horizon(bar_interval_ns=0)


def test_the_breakeven_edge_is_the_cost_of_a_round_trip() -> None:
    """A position opened and closed within its holding bar breaks even when the move covers the
    round trip exactly. That is the cost line, and stating it is not a new model."""
    from pips.search.funnel import breakeven_edge

    assert breakeven_edge(0.0005) == pytest.approx(0.0005)


def test_a_zero_cost_line_has_no_breakeven_edge() -> None:
    """Zero is arithmetically true and reads as "any edge at all will do", which is a claim
    about implementation feasibility that a costless model cannot support."""
    from pips.search.funnel import breakeven_edge

    assert breakeven_edge(0.0) is None


def test_a_negative_cost_line_is_refused() -> None:
    from pips.search.funnel import breakeven_edge

    with pytest.raises(ValueError, match="cost"):
        breakeven_edge(-0.001)


# ------------------------------------- concentration: measured, still ungated -----


def test_the_share_is_the_largest_single_name() -> None:
    """§12.2 asks whether a single stock dominates net P&L. This is that fraction."""
    from pips.search.funnel import concentration_share

    per_name = {"A": (0.6, 0), "B": (0.3, 0), "C": (0.1, 0)}
    assert concentration_share(per_name, cost_per_round_trip=0.0) == pytest.approx(0.6)


def test_costs_are_charged_to_the_name_that_traded() -> None:
    """A name that traded more pays more, so the share is of NET and not gross contribution.

    Sharing costs evenly, or ignoring them, credits a churner with edge it spent on commission.
    """
    from pips.search.funnel import concentration_share

    per_name = {"A": (0.6, 100), "B": (0.3, 0)}
    # A nets 0.6 - 100*0.002 = 0.4; B nets 0.3. Total 0.7, so A holds 4/7.
    assert concentration_share(per_name, cost_per_round_trip=0.002) == pytest.approx(4 / 7)


def test_a_single_name_is_total_concentration() -> None:
    from pips.search.funnel import concentration_share

    assert concentration_share({"A": (0.5, 0)}, cost_per_round_trip=0.0) == pytest.approx(1.0)


def test_a_non_positive_total_has_no_share() -> None:
    """The share INVERTS against a negative total: a name that lost less takes the larger
    fraction, so 0.9 would read as dominance when it means "lost the least".

    This is why the field is absent on the fixture data rather than reported as a number — the
    candidates all lose money once costs are applied.
    """
    from pips.search.funnel import concentration_share

    assert concentration_share({"A": (-0.1, 0), "B": (-0.5, 0)}, cost_per_round_trip=0.0) is None
    assert concentration_share({"A": (0.2, 0), "B": (-0.2, 0)}, cost_per_round_trip=0.0) is None


def test_no_attribution_has_no_share() -> None:
    from pips.search.funnel import concentration_share

    assert concentration_share({}, cost_per_round_trip=0.0) is None


def test_a_losing_name_does_not_take_a_negative_share() -> None:
    """Only the LARGEST contributor is reported; a loser's negative fraction is not the answer
    to "does a single stock dominate"."""
    from pips.search.funnel import concentration_share

    share = concentration_share({"A": (1.0, 0), "B": (-0.5, 0)}, cost_per_round_trip=0.0)
    assert share == pytest.approx(2.0), "A contributed 1.0 of a 0.5 total"
