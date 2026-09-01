"""Ex-post selection by realized sign  (§6 M16, A06's falsifier).

A06 pre-registered *"Reject if continuation and reversal rules are selected ex post by realized
sign"* — the last structural falsifier, and the one where the obvious test is wrong.

**The obvious test is wrong.** One might check whether the A05/A06 assignment correlates with
what actually happened. But if the alphas have any edge at all, it should: names A05 claims
ought to continue and names A06 claims ought to revert. Correlation with the outcome is the
intended result, not the crime.

The crime has a different signature. Ex-post selection means the assignment **depends on** the
outcome — so it is caught by changing the outcome and watching the assignment move. Perturb
only bars strictly after the decision, recompute, and see whether any name changed hands. A
rule that reads the future partitions differently when the future differs; one that cannot see
it does not.

That also makes this an end-to-end check of the as-of machinery rather than a restatement of
it. `AsOfPanelView` is supposed to make this impossible; this verifies the guarantee instead of
trusting it.

Two vacuity traps, both learned the hard way:

**No bars after the decision means nothing to perturb.** At the last bar there is no future,
the check has nothing to change, and a clean pass there would be a pass over an untouched
panel. `ran=False`, and not-run is not a pass.

**The perturbation must be verified to have changed the frame** before any conclusion is drawn
from the partition matching.
"""

from __future__ import annotations

import polars as pl
import pytest

from pips.validation.ex_post_selection import partition_invariance

NS = 1_000_000_000
MIN = 60 * NS
START = 1_780_285_560_000_000_000
DECISION = START + 9 * MIN


def panel(n: int = 20) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol, drift in (("AAA", 40), ("BBB", -40)):
        for i in range(n):
            rows.append(
                {
                    "close_ts_ns": START + i * MIN,
                    "symbol": symbol,
                    "close_paise": 100_000 + i * drift,
                    "volume": 1_000,
                }
            )
    return pl.DataFrame(rows).sort(["close_ts_ns", "symbol"])


def causal_assign(frame: pl.DataFrame) -> dict[str, str]:
    """Partitions on visible history only — the correct shape.

    Reads bars at or before the decision and assigns by the sign of the move so far.
    """
    visible = frame.filter(pl.col("close_ts_ns") <= DECISION)
    out: dict[str, str] = {}
    for symbol in sorted(set(visible["symbol"].to_list())):
        closes = visible.filter(pl.col("symbol") == symbol).sort("close_ts_ns")["close_paise"]
        out[symbol] = "A05" if closes[-1] >= closes[0] else "A06"
    return out


def peeking_assign(frame: pl.DataFrame) -> dict[str, str]:
    """Partitions on the REALIZED outcome — the crime, stated plainly."""
    out: dict[str, str] = {}
    for symbol in sorted(set(frame["symbol"].to_list())):
        closes = frame.filter(pl.col("symbol") == symbol).sort("close_ts_ns")["close_paise"]
        out[symbol] = "A05" if closes[-1] >= closes[0] else "A06"
    return out


# ------------------------------------------------------------ the check ----------------


def test_a_causal_partition_does_not_move_when_only_the_future_moves() -> None:
    verdict = partition_invariance(causal_assign, panel(), decision_ts=DECISION)
    assert verdict.ran
    assert verdict.invariant
    assert verdict.reassigned == ()


def test_a_partition_that_reads_the_outcome_is_caught() -> None:
    """The control, and it must be here.

    Without a rule that fails, "invariant" is what this function would say about everything,
    and the check would certify ex-post selection as the absence of it.
    """
    verdict = partition_invariance(peeking_assign, panel(), decision_ts=DECISION)
    assert verdict.ran
    assert not verdict.invariant
    assert verdict.reassigned != ()


def test_the_verdict_names_which_instrument_changed_hands() -> None:
    verdict = partition_invariance(peeking_assign, panel(), decision_ts=DECISION)
    assert any(name in {"AAA", "BBB"} for name, _, _ in verdict.reassigned)


def test_only_bars_after_the_decision_are_perturbed() -> None:
    """Perturbing a visible bar would change the partition for a legitimate reason.

    Then a correct rule would look like a cheating one, and the check would reject exactly the
    alphas it exists to protect.
    """
    verdict = partition_invariance(causal_assign, panel(), decision_ts=DECISION)
    assert verdict.bars_perturbed > 0
    assert verdict.invariant, "a causal rule must survive its own future changing"


# ------------------------------------------------------------ vacuity ------------------


def test_no_future_bars_means_the_check_cannot_run() -> None:
    """At the last bar there is no future to perturb.

    A clean pass there is a pass over an untouched panel — the vacuity this project keeps
    finding in its own checks.
    """
    frame = panel()
    last = int(frame["close_ts_ns"].max())  # type: ignore[arg-type]
    verdict = partition_invariance(causal_assign, frame, decision_ts=last)
    assert verdict.ran is False
    assert verdict.invariant is False, "could not run is not invariant"
    assert "no bars after" in verdict.note


def test_the_check_runs_on_an_ordinary_panel() -> None:
    # (superseded: the perturbation is now a mirror, so "zero magnitude" is expressed as a
    # future that mirrors onto itself — see test_a_flat_future_cannot_be_mirrored_and_is_refused)
    verdict = partition_invariance(causal_assign, panel(), decision_ts=DECISION)
    assert verdict.ran


def test_an_empty_panel_is_refused() -> None:
    with pytest.raises(ValueError, match="no bars"):
        partition_invariance(causal_assign, panel().head(0), decision_ts=DECISION)


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "ex-post-selection" in CHECK_REGISTRY
    resolve_check("ex-post-selection")


def peeks_at_future_direction(frame: pl.DataFrame) -> dict[str, str]:
    """Reads the future's DIRECTION, not its level — invisible to a uniform shift.

    A level shift moves every post-decision bar by the same amount, so every difference
    between them is unchanged and a rule reading the future's shape sees nothing. This is the
    blind spot that the original additive perturbation had, found by noticing that a mutation
    perturbing ALL bars still left the causal rule invariant: if a uniform shift cannot move a
    difference-based rule, it cannot catch one either.
    """
    out: dict[str, str] = {}
    for symbol in sorted(set(frame["symbol"].to_list())):
        rows = frame.filter(pl.col("symbol") == symbol).sort("close_ts_ns")
        future = rows.filter(pl.col("close_ts_ns") > DECISION)["close_paise"]
        out[symbol] = "A05" if future[-1] >= future[0] else "A06"
    return out


def test_a_rule_reading_the_futures_direction_is_caught() -> None:
    """The case a level shift would have missed entirely.

    Mirroring the future about the last visible close flips its direction while preserving
    every magnitude, so a rule reading direction changes its answer and a causal rule cannot
    notice at all.
    """
    verdict = partition_invariance(peeks_at_future_direction, panel(), decision_ts=DECISION)
    assert verdict.ran
    assert not verdict.invariant, "a rule reading the future's shape must be caught"


def test_a_flat_future_cannot_be_mirrored_and_is_refused() -> None:
    """The vacuity case for a mirroring perturbation.

    A future that never moves mirrors onto itself, so nothing changed and any conclusion would
    be about a panel nobody perturbed — the same hole a zero-magnitude shift left.
    """
    rows: list[dict[str, object]] = []
    for symbol in ("AAA", "BBB"):
        for i in range(20):
            close = 100_000 + (i * 40 if START + i * MIN <= DECISION else 9 * 40)
            rows.append(
                {
                    "close_ts_ns": START + i * MIN,
                    "symbol": symbol,
                    "close_paise": close,
                    "volume": 1_000,
                }
            )
    flat_future = pl.DataFrame(rows).sort(["close_ts_ns", "symbol"])
    with pytest.raises(ValueError, match="changed no value"):
        partition_invariance(causal_assign, flat_future, decision_ts=DECISION)
