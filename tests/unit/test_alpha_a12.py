"""A12 -- intraday seasonal residual (T1), [C-SPEC-01].

The alpha's own fit protocol names the artefact it must not become: *"Slot means are never
reported unshrunk — an unshrunk slot mean over few sessions is the artefact this alpha must
not become."* Its declared null is exactly that artefact: "unshrunk slot mean".

This is the most seductive of the nine. Slice a return series by clock slot and some slot will
have a large mean, always, in any data — that is what finite samples do. Report it raw and the
alpha is a machine for finding noise and calling it a schedule. The hypothesis is careful about
this too: *"an isolated slot spike is the NULL this must be distinguished from, not evidence
for it."*

So the load-bearing tests are about the shrinkage, not the signal:

- a slot estimated from few sessions is pulled hard toward its parent;
- the same raw mean from many sessions is pulled far less;
- **no slot mean is ever reported raw**, whatever its history.

The missingness clauses follow the family: *"insufficient session history => no slot estimate,
NOT a zero"*, and a bar outside the continuous session has no slot at all.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from pips.alphas.spec import AlphaSpec, load_alpha_spec
from pips.alphas.t1.a12 import A12Params, compute
from pips.core.asof import AsOfPanelView

NS = 1_000_000_000
MIN = 60 * NS
# 2026-06-01 09:16:00 IST — the close label of the session's first one-minute bar.
FIRST_LABEL = 1_780_285_560_000_000_000
DAY = 24 * 60 * 60 * NS
SPEC_DIR = Path("config/search_spaces")
SLOT_OFFSETS = (0, 5, 10)  # 09:16, 09:21, 09:26 -> 5-minute slots 0, 1, 2


def spec() -> AlphaSpec:
    return load_alpha_spec(SPEC_DIR / "A12_intraday_seasonal.yaml")


def build(per_session: dict[str, list[list[int]]], start: int = FIRST_LABEL) -> pl.DataFrame:
    """`{symbol: [[close, close, close], ...]}` — one inner list per session."""
    rows: list[dict[str, object]] = []
    for symbol, sessions in per_session.items():
        for day, closes in enumerate(sessions):
            for offset, close in zip(SLOT_OFFSETS, closes, strict=True):
                rows.append(
                    {
                        "close_ts_ns": start + day * DAY + offset * MIN,
                        "symbol": symbol,
                        "close_paise": close,
                        "high_paise": close + 5,
                        "low_paise": close - 5,
                        "volume": 1_000,
                    }
                )
    return pl.DataFrame(rows).sort(["close_ts_ns", "symbol"])


def sessions_where(
    n: int, slot_bump: dict[int, int] | None = None, jitter_on: bool = True
) -> list[list[int]]:
    """`n` sessions of three slots, with an optional per-slot price bump.

    The bump is applied to one slot's close, so the return INTO that slot carries a consistent
    sign session after session — a seasonal pattern by construction.

    IT VARIES SESSION TO SESSION, deterministically, and that is essential. A bump identical
    in every session gives the slot ZERO within-slot variance, which trips the plugin's
    degenerate guard and shrinks the estimate fully to its parent — so every weight came out
    at exactly 0, and the "more sessions earn more weight" test was silently comparing two
    parent means rather than any shrinkage at all. A perfectly repeating seasonal is not a
    market; it is a metronome with a schedule.
    """
    bump = slot_bump or {}
    out: list[list[int]] = []
    for session in range(n):
        jitter = ((session % 7) - 3) if jitter_on else 0  # mean zero over each period of 7
        out.append(
            [
                100_000 + b + (jitter * b // 6 if b else 0)
                for b in (bump.get(i, 0) for i in range(3))
            ]
        )
    return out


def params(**over: object) -> A12Params:
    base: dict[str, object] = {
        "clock_bin_minutes": 5,
        "history_sessions": 60,
        "hold_minutes": 30,
        "horizon_ns": 30 * MIN,
    }
    base.update(over)
    return A12Params(**base)  # type: ignore[arg-type]


def scores(frame: pl.DataFrame, **over: object) -> dict[str, Decimal]:
    view = AsOfPanelView(frame, decision_ts=int(frame["close_ts_ns"].max()))  # type: ignore[arg-type]
    return {f.instrument_id: f.expected_return_bps for f in compute(view, params(**over), spec())}


# ------------------------------------------------------------ shrinkage ----------------


def test_no_slot_mean_is_ever_reported_unshrunk() -> None:
    """The fit protocol, stated absolutely, tested absolutely.

    Whatever the history, the reported score must sit strictly between the parent mean and the
    raw slot mean. Equality with the raw mean is the declared null model — "unshrunk slot
    mean, the artefact this must beat" — so an implementation that ever returns it has become
    its own null.
    """
    frame = build({"AAA": sessions_where(80, {2: 900}), "BBB": sessions_where(80)})
    raw, shrunk = compute_raw_and_shrunk(frame)
    assert shrunk != 0
    assert abs(shrunk) < abs(raw), (
        f"reported {shrunk} is not shrunk relative to the raw slot mean {raw}"
    )


def compute_raw_and_shrunk(frame: pl.DataFrame) -> tuple[Decimal, Decimal]:
    from pips.alphas.t1.a12 import slot_estimates

    view = AsOfPanelView(frame, decision_ts=int(frame["close_ts_ns"].max()))  # type: ignore[arg-type]
    estimates = slot_estimates(view, params())
    estimate = estimates["AAA"]
    return estimate.raw_mean, estimate.shrunk_mean


def test_a_slot_seen_in_few_sessions_is_pulled_harder_than_one_seen_in_many() -> None:
    """The mechanism, isolated: same raw slot mean, different amounts of evidence.

    A slot mean of the same size means far less when it comes from 8 sessions than from 200.
    An implementation that shrinks by a fixed factor — or not at all — treats them alike, and
    treating them alike is how an isolated spike becomes a signal.
    """
    few = build({"AAA": sessions_where(62, {2: 900}), "BBB": sessions_where(62)})
    many = build({"AAA": sessions_where(240, {2: 900}), "BBB": sessions_where(240)})

    few_raw, few_shrunk = compute_raw_and_shrunk(few)
    many_raw, many_shrunk = compute_raw_and_shrunk(many)

    assert few_raw != 0 and many_raw != 0
    few_weight = abs(few_shrunk) / abs(few_raw)
    many_weight = abs(many_shrunk) / abs(many_raw)
    assert many_weight > few_weight, (
        "more independent sessions must earn more of the raw slot mean; got "
        f"{few_weight} on 62 sessions and {many_weight} on 240"
    )


# ------------------------------------------------------------ missingness --------------


def test_insufficient_session_history_yields_no_forecast() -> None:
    # "insufficient session history => no slot estimate, NOT a zero". A zero would be a
    # measured no-position; there is nothing measured here at all.
    frame = build({"AAA": sessions_where(10, {2: 900}), "BBB": sessions_where(10)})
    assert scores(frame) == {}


def test_a_bar_outside_the_continuous_session_has_no_slot() -> None:
    """A pre-open or post-close print must not land in a clock slot.

    Post-close prints are a real Breeze behaviour — the M3 probe found the vendor returns them
    when the window allows — and one landing in the 15:25 slot would attach an auction print
    to an intraday seasonal pattern that has nothing to do with it.
    """
    from pips.alphas.t1.a12 import slot_of

    assert slot_of(9, 16, bin_minutes=5) == 0
    assert slot_of(9, 20, bin_minutes=5) == 0
    assert slot_of(9, 21, bin_minutes=5) == 1
    assert slot_of(15, 30, bin_minutes=5) == 74
    assert slot_of(9, 15, bin_minutes=5) is None, "09:15 labels the pre-open, not a bar"
    assert slot_of(9, 10, bin_minutes=5) is None
    assert slot_of(15, 40, bin_minutes=5) is None


# ------------------------------------------------------------ domain -------------------


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("clock_bin_minutes", 3),
        ("clock_bin_minutes", 20),
        ("history_sessions", 30),
        ("history_sessions", 400),
        ("hold_minutes", 1),
        ("hold_minutes", 90),
    ],
)
def test_a_parameter_outside_the_pre_registered_domain_is_refused(field: str, bad: object) -> None:
    with pytest.raises(ValueError, match=field.split("_")[0]):
        params(**{field: bad})


def test_the_plugin_reads_nothing_beyond_the_decision_bar() -> None:
    frame = build({"AAA": sessions_where(80, {2: 900}), "BBB": sessions_where(80)})
    view = AsOfPanelView(frame, decision_ts=int(frame["close_ts_ns"].max()))  # type: ignore[arg-type]
    compute(view, params(), spec())
    latest = view.max_source_ts()
    assert latest is not None, "the fixture must be visible, or this proves nothing"
    assert latest <= view.decision_ts


def sessions_with_spike(n: int, slot: int, spike: int) -> list[list[int]]:
    """`n` flat sessions except ONE, which carries the whole bump in a single session."""
    out: list[list[int]] = []
    for session in range(n):
        closes = [100_000, 100_000, 100_000]
        if session == 0:
            closes[slot] += spike
        out.append(closes)
    return out


def sessions_spread(n: int, slot: int, spike: int) -> list[list[int]]:
    """The same TOTAL bump as :func:`sessions_with_spike`, spread evenly over every session."""
    per = spike // n
    out: list[list[int]] = []
    for session in range(n):
        closes = [100_000, 100_000, 100_000]
        jitter = (session % 7) - 3
        closes[slot] += per + jitter * per // 6
        out.append(closes)
    return out


def test_an_isolated_spike_is_shrunk_away_while_a_steady_pattern_survives() -> None:
    """The hypothesis, tested as written.

    *"An isolated slot spike is the NULL this must be distinguished from, not evidence for
    it."* These two fixtures have the SAME raw slot mean. One got there from a single session
    that moved 8%; the other from eighty sessions that each moved 0.1%. Only the second is a
    schedule. An estimator that reports them alike is the "unshrunk slot mean" null, and it
    would report the spike as an alpha.
    """
    spike = build({"AAA": sessions_with_spike(80, 2, 8_000), "BBB": sessions_where(80)})
    steady = build({"AAA": sessions_spread(80, 2, 8_000), "BBB": sessions_where(80)})

    spike_raw, spike_shrunk = compute_raw_and_shrunk(spike)
    steady_raw, steady_shrunk = compute_raw_and_shrunk(steady)
    spike_kept = abs(spike_shrunk) / abs(spike_raw)
    steady_kept = abs(steady_shrunk) / abs(steady_raw)

    # THE CONTRAST IS THE CLAIM, not an absolute level. My first version demanded the spike
    # keep under a tenth of its raw mean — a number I guessed rather than derived. The
    # estimator keeps about 39%, which is the correct empirical-Bayes answer for a mean that
    # sits roughly one standard error from zero, and tightening the estimator to hit an
    # invented threshold would be fitting it to the test.
    #
    # Compute-stage shrinkage also does not have to do all the work: A12's own falsifier
    # ("reject isolated day-of-week or slot spikes AFTER family-wise correction") puts the
    # rest of the burden on validation, by design.
    assert spike_kept < Decimal("0.5"), f"a single session must not carry a slot: {spike_kept}"
    assert steady_kept > Decimal("0.9"), f"a steady pattern must survive: {steady_kept}"
    assert steady_kept > 2 * spike_kept, (
        f"the two must be DISTINGUISHED — spike kept {spike_kept}, steady kept {steady_kept}"
    )


def test_a_slot_with_no_measurable_noise_is_shrunk_fully_not_reported_raw() -> None:
    """Zero within-slot variance is unearned confidence, not perfect evidence.

    A slot whose residual is byte-identical in every session has a within-variance of zero,
    which the empirical-Bayes weight would read as infinite precision and report RAW — the
    declared null model. Claiming zero noise from a finite sample is exactly the overconfidence
    the shrinkage exists to prevent, so it shrinks fully to the parent instead.

    This case exists here on purpose. It arrived by accident first: every fixture in this file
    was a perfect metronome, so every weight was zero and the shrinkage tests were comparing
    parent means. Adding jitter fixed those and removed the only coverage of this branch — a
    mutation run said so.
    """
    from pips.alphas.t1.a12 import slot_estimates

    frame = build(
        {
            "AAA": sessions_where(80, {2: 900}, jitter_on=False),
            "BBB": sessions_where(80, jitter_on=False),
        }
    )
    view = AsOfPanelView(frame, decision_ts=int(frame["close_ts_ns"].max()))  # type: ignore[arg-type]
    estimate = slot_estimates(view, params())["AAA"]

    assert estimate.raw_mean != 0, "the fixture must have a raw mean, or this proves nothing"
    assert estimate.weight == 0
    assert estimate.shrunk_mean == estimate.parent_mean
