"""A07 -- opening-range breakout (T1), [C-SPEC-01].

Three clauses in the spec do the work, and all three are of the same kind: **a missing input
is not a default one.**

`opening_range`  — *"session shorter than the endpoint => no range, no forecast"*
`volatility_buffer` — *"no ATR estimate => no buffer, and therefore no signal"*
`breakout_flag` — *"a breach on the same bar as the range endpoint is not a breach"*

The second is the easiest to get wrong in the flattering direction. "No ATR" invites a zero
buffer, which is not "no signal" — it is the *widest possible* signal, firing on every marginal
touch of the raw range. The spec says no forecast, and it says so because the falsifier below
it is "reject if small changes to range_end or buffer reverse the result": an alpha that
silently falls back to a zero buffer has already answered that falsifier by construction.

The third is the causality guard, and its falsifier names the harm directly — *"reject if most
P&L comes from same-bar fills"*. If the bar that closes the range can also be the breakout bar,
the strategy is deciding on a price it is simultaneously using to define the threshold.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from pips.alphas.spec import AlphaSpec, load_alpha_spec
from pips.alphas.t1.a07 import A07Params, compute
from pips.core.asof import AsOfPanelView

NS = 1_000_000_000
MIN = 60 * NS
SESSION_1 = 1_780_285_560_000_000_000
DAY = 24 * 60 * 60 * NS
SPEC_DIR = Path("config/search_spaces")


def spec() -> AlphaSpec:
    return load_alpha_spec(SPEC_DIR / "A07_opening_range_breakout.yaml")


def bars(
    symbol: str, start_ts: int, closes: list[int], volumes: list[int] | None = None, span: int = 20
) -> list[dict[str, object]]:
    vols = volumes if volumes is not None else [1_000] * len(closes)
    return [
        {
            "close_ts_ns": start_ts + i * MIN,
            "symbol": symbol,
            "close_paise": c,
            "high_paise": c + span,
            "low_paise": c - span,
            "volume": v,
        }
        for i, (c, v) in enumerate(zip(closes, vols, strict=True))
    ]


def panel(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows).sort(["close_ts_ns", "symbol"])


PRIOR = [100_000 + (i % 3) * 30 for i in range(40)]


def two_day(
    today_closes: list[int],
    today_volumes: list[int] | None = None,
    prior: list[int] | None = None,
    symbol: str = "AAA",
    prior_span: int = 20,
) -> pl.DataFrame:
    rows = bars(symbol, SESSION_1, PRIOR if prior is None else prior, span=prior_span)
    rows += bars(symbol, SESSION_1 + DAY, today_closes, today_volumes)
    # A second name so the panel is a cross-section, as every other plugin sees.
    rows += bars("BBB", SESSION_1, PRIOR)
    rows += bars("BBB", SESSION_1 + DAY, [100_000] * len(today_closes))
    return panel(rows)


def view(frame: pl.DataFrame, minutes_into_today: int) -> AsOfPanelView:
    return AsOfPanelView(frame, decision_ts=SESSION_1 + DAY + minutes_into_today * MIN)


def params(**over: object) -> A07Params:
    base: dict[str, object] = {
        "range_end_minutes": 5,
        "buffer_atr": Decimal("0.5"),
        "hold_minutes": 30,
        "min_participation": Decimal("1.5"),
        "horizon_ns": 30 * MIN,
    }
    base.update(over)
    return A07Params(**base)  # type: ignore[arg-type]


def scores(frame: pl.DataFrame, minutes: int, **over: object) -> dict[str, Decimal]:
    return {
        f.instrument_id: f.expected_return_bps
        for f in compute(view(frame, minutes), params(**over), spec())
    }


# ------------------------------------------------------ the pre-registered domain -------


def test_a_range_end_outside_the_four_predeclared_values_is_refused() -> None:
    # The fit protocol: "range_end is one of four PREDECLARED values, not a continuous search."
    # Allowing 7 or 12 turns a four-point grid into a search over the range endpoint, which is
    # what the first falsifier ("small changes to range_end reverse the result") is aimed at.
    for bad in (1, 7, 12, 45):
        with pytest.raises(ValueError, match="predeclared"):
            params(range_end_minutes=bad)


def test_a_buffer_outside_zero_to_one_atr_is_refused() -> None:
    for bad in (Decimal("-0.1"), Decimal("1.5")):
        with pytest.raises(ValueError, match="buffer"):
            params(buffer_atr=bad)


# ------------------------------------------------------ missing is not default ----------


def test_a_breach_on_the_range_endpoint_bar_is_not_a_breach() -> None:
    """The causality guard, and its falsifier is 'most P&L comes from same-bar fills'.

    A 5-minute range is bars 0-4, so at 4 minutes in the LAST VISIBLE BAR IS THE ENDPOINT. A
    spike there cannot be a breach of a range it is itself defining — and the plugin must
    produce no forecast at all, not a zero, because nothing has been measured yet.

    (The first version of this test put the spike on bar 5 and decided at minute 5, which is
    one bar AFTER the endpoint — a perfectly ordinary breach, so it was asserting the opposite
    of what its own name claimed.)
    """
    closes = [100_000] * 4 + [200_000]  # bar index 4 is the endpoint AND the spike
    frame = two_day(closes, today_volumes=[1_000] * 4 + [50_000])
    assert "AAA" not in scores(frame, 4)


def test_the_same_move_one_bar_later_is_a_breach() -> None:
    # The control. Without it the test above passes for a plugin that never fires at all.
    closes = [100_000] * 6 + [200_000]
    frame = two_day(closes, today_volumes=[1_000] * 6 + [50_000])
    assert scores(frame, 6)["AAA"] > 0


def test_no_atr_estimate_yields_no_forecast_not_a_zero_buffer() -> None:
    """A flat prior session gives no ATR, and no ATR means NO SIGNAL — not a zero buffer.

    A zero buffer is not the absence of a buffer; it is the widest possible signal, firing on
    every marginal touch of the raw range. Falling back to it would answer the alpha's own
    "small changes to the buffer reverse the result" falsifier by construction.
    """
    # span=0 so high == low == close: a session with no true range at all. The first version
    # of this test used a flat CLOSE series while `bars()` still added a 40-paise high/low
    # span, so the ATR was never zero and the test could not fail.
    flat = [100_000] * 40
    closes = [100_000] * 6 + [200_000]
    frame = two_day(closes, today_volumes=[1_000] * 6 + [50_000], prior=flat, prior_span=0)
    # BBB still has a live prior session, so an empty result would prove nothing on its own.
    assert "AAA" not in scores(frame, 6)


def test_a_session_shorter_than_the_range_endpoint_yields_no_forecast() -> None:
    frame = two_day([100_000] * 3)
    assert scores(frame, 2) == {}


# ------------------------------------------------------ the breakout itself -------------


def test_a_breach_inside_the_buffer_is_not_a_breakout() -> None:
    """The buffer has to actually widen the boundary.

    This close clears the raw opening range but sits inside range + 0.5 ATR.

    The pairing with `buffer_atr=0` is what gives the test teeth. The first version asserted
    only the zero, with a close that never cleared the RAW range either — so dropping the
    buffer entirely passed it, and a mutation run said so. Asserting that the same bar DOES
    score once the buffer is removed pins the buffer as the thing making the difference.
    """
    # Range over bars 0-4: high 100_070 (close 100_050 + 20 span), low 99_980.
    closes = [100_000, 100_050, 100_000, 100_050, 100_000, 100_000, 100_075]
    frame = two_day(closes, today_volumes=[1_000] * 6 + [50_000])

    assert scores(frame, 6)["AAA"] == 0, "100_075 is inside 100_070 + 0.5 ATR"
    assert scores(frame, 6, buffer_atr=Decimal(0))["AAA"] > 0, (
        "with no buffer the same bar clears the raw range — so the zero above is the "
        "buffer's doing, not an absence of any breach at all"
    )


def test_a_breakout_without_abnormal_participation_is_flat() -> None:
    # `breakout_flag` is "close beyond range +/- buffer, WITH abnormal participation". The
    # participation leg is part of the flag, not a later filter — and "breakout without the
    # participation filter" is a declared null model, so the two must be distinguishable.
    closes = [100_000] * 6 + [200_000]
    frame = two_day(closes, today_volumes=[1_000] * 7)
    assert scores(frame, 6)["AAA"] == 0


def test_a_downward_breach_scores_negative() -> None:
    closes = [100_000] * 6 + [50_000]
    frame = two_day(closes, today_volumes=[1_000] * 6 + [50_000])
    assert scores(frame, 6)["AAA"] < 0


def test_a_panel_without_high_and_low_is_a_configuration_error_not_a_quiet_no_signal() -> None:
    """A whole panel missing high/low is a misconfiguration, and must say so.

    Per-symbol "no ATR" is a data gap the spec answers with "no signal". A panel that has no
    high/low COLUMNS AT ALL is a different thing entirely, and letting it fall through the
    same path would report a silently disabled alpha as a working one that found nothing.
    """
    frame = panel(
        [
            {
                "close_ts_ns": SESSION_1 + i * MIN,
                "symbol": "AAA",
                "close_paise": 100_000,
                "volume": 1_000,
            }
            for i in range(40)
        ]
    )
    with pytest.raises(ValueError, match="high_paise"):
        compute(view(frame, 6), params(), spec())


def test_the_plugin_reads_nothing_beyond_the_decision_bar() -> None:
    closes = [100_000] * 6 + [200_000]
    frame = two_day(closes, today_volumes=[1_000] * 6 + [50_000])
    v = view(frame, 6)
    compute(v, params(), spec())
    latest = v.max_source_ts()
    assert latest is not None, "the fixture must be visible, or this proves nothing"
    assert latest <= v.decision_ts
