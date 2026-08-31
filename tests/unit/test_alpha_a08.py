"""A08 -- compression-to-expansion continuation (T1), [C-SPEC-01].

The spec states its own trap in the hypothesis: *"The claim is the directional component AFTER
controlling for unconditional volatility clustering — **expansion alone is a volatility
forecast, not an alpha**."* Its declared parent null is "a pure volatility forecast with no
direction", and its first falsifier is "reject if direction adds no information beyond a
volatility forecast".

Volatility clustering is real, strong and free: quiet periods are followed by quiet periods and
bursts by bursts. An alpha that scores raw expansion magnitude will look like it works, because
it is forecasting variance — which is genuinely predictable and worth nothing directionally.

So the load-bearing test here is not that a burst scores. It is that **two names with the same
absolute expansion score differently when their own volatilities differ**, and the quieter one
scores larger. That is what dividing by the volatility forecast buys, and without it the two
would tie — which is the degenerate alpha the spec is warning about, passing every other test
in this file.

The three missingness clauses are the family's usual shape and all mean *no forecast*, never a
zero: no percentile without history, no trigger without a MAD estimate, and — the sharpest —
*"no volatility forecast => no directional claim, since direction is DEFINED relative to it."*
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from pips.alphas.spec import AlphaSpec, load_alpha_spec
from pips.alphas.t1.a08 import A08Params, compute
from pips.core.asof import AsOfPanelView

NS = 1_000_000_000
MIN = 60 * NS
START = 1_780_285_560_000_000_000
SPEC_DIR = Path("config/search_spaces")


def spec() -> AlphaSpec:
    return load_alpha_spec(SPEC_DIR / "A08_compression_expansion.yaml")


def bars(symbol: str, closes: list[int], volumes: list[int]) -> list[dict[str, object]]:
    return [
        {
            "close_ts_ns": START + i * MIN,
            "symbol": symbol,
            "close_paise": c,
            "high_paise": c + 5,
            "low_paise": c - 5,
            "volume": v,
        }
        for i, (c, v) in enumerate(zip(closes, volumes, strict=True))
    ]


def wobble(n: int, amp: int, base: int = 100_000) -> list[int]:
    """`n` closes oscillating with amplitude `amp`, with a deterministic irregularity.

    The irregularity is not decoration. A perfectly regular alternation moves EXACTLY the same
    amount every bar, so the median absolute deviation of |return| is zero — the plugin then
    has no scale on which to call an expansion abnormal, correctly declines to trigger, and
    every test built on that fixture silently produces no forecast at all. Real series are not
    metronomes, and a fixture that is one tests a market that does not exist.
    """
    return [base + (i % 2) * amp + (i % 3) * (amp // 4) for i in range(n)]


def compressed_then_burst(
    loud_amp: int = 400, quiet_amp: int = 20, burst: int = 5_000, window: int = 45
) -> tuple[list[int], list[int]]:
    """A loud history, then a quiet window, then one directional expansion bar.

    Two things here are deliberate and were wrong in the first draft:

    VOLUME VARIES. A constant-volume history has a median absolute deviation of zero, so
    "abnormal by e0 MADs" has no scale and the plugin correctly declines to trigger at all —
    which made every fixture in this file silently produce no forecast. Real volume varies;
    a fixture that does not is testing a market that does not exist.

    THE BURST IS RELATIVE to the last close, not absolute. Anchoring it to 100,000 made the
    up and down cases asymmetric (the quiet window does not end at exactly 100,000), so the
    two scores could not be exact opposites and the symmetry assertion was unwinnable.

    THE QUIET WINDOW IS LONGER THAN THE COMPRESSION WINDOW (45 vs 30). At 30 it began exactly
    where the loud history ended, so the single loud->quiet transition bar sat inside every
    name's compression window and dominated its standard deviation — squashing a genuine 10x
    volatility difference down to 2x and making the ratio assertion measure the seam rather
    than the names.
    """
    closes = wobble(120, loud_amp) + wobble(window, quiet_amp)
    closes.append(closes[-1] + burst)
    volumes = [1_000 + (i % 7) * 60 for i in range(120 + window)] + [80_000]
    return closes, volumes


def panel(*named: tuple[str, list[int], list[int]]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol, closes, volumes in named:
        rows += bars(symbol, closes, volumes)
    return pl.DataFrame(rows).sort(["close_ts_ns", "symbol"])


def params(**over: object) -> A08Params:
    base: dict[str, object] = {
        "compression_window_m": 30,
        "compression_percentile_c0": 30,
        "expansion_threshold_e0_mad": Decimal(2),
        "hold_minutes": 30,
        "horizon_ns": 30 * MIN,
    }
    base.update(over)
    return A08Params(**base)  # type: ignore[arg-type]


def scores(frame: pl.DataFrame, **over: object) -> dict[str, Decimal]:
    view = AsOfPanelView(frame, decision_ts=int(frame["close_ts_ns"].max()))  # type: ignore[arg-type]
    return {f.instrument_id: f.expected_return_bps for f in compute(view, params(**over), spec())}


# --------------------------------------------- the alpha must not be a vol forecast -----


def test_the_same_expansion_scores_larger_for_the_quieter_name() -> None:
    """The test the whole alpha turns on.

    The two names share an IDENTICAL long history and an identical 5,000-paise expansion. The
    only difference is how quiet their compression window got: 20 paise a bar versus 200. For
    the quieter one the move is extraordinary; for the other it is merely large. A score that
    treats them alike is forecasting variance, which is predictable and directionally
    worthless — the "pure volatility forecast with no direction" the spec names as the parent
    this must beat.

    The first version of this test also made the loud name's whole history ten times noisier,
    which confounded the comparison: that name then failed the expansion gate outright (a 5%
    move is not abnormal against a 4% median) and scored zero for a reason unrelated to
    normalisation. Varying one thing is the point.
    """
    quiet_closes, quiet_vol = compressed_then_burst(quiet_amp=20)
    noisy_closes, noisy_vol = compressed_then_burst(quiet_amp=200)
    got = scores(panel(("QUIET", quiet_closes, quiet_vol), ("NOISY", noisy_closes, noisy_vol)))
    assert got["QUIET"] > 0 and got["NOISY"] > 0, f"both must trigger, got {got}"

    # A RATIO, not an ordering. `assert QUIET > NOISY` survived removing the normalisation
    # entirely: the two raw returns differ by a hair (the quiet window ends at a slightly
    # lower price, so the same 5,000 paise is a marginally larger fraction) and that hair
    # happens to point the right way. The comparison was true under the alpha and under the
    # variance forecast it must not be, which makes it no evidence at all.
    #
    # The compression windows differ 10x in amplitude, so normalisation must separate the
    # scores by something of that order. Without it the ratio is ~1.002.
    assert got["QUIET"] > 5 * got["NOISY"], (
        "an identical expansion must mean roughly 10x more for a name that has been 10x "
        f"quieter; a ratio near 1 is a volatility forecast wearing an alpha's name — {got}"
    )


def test_direction_is_carried_not_discarded() -> None:
    # "expansion magnitude with random sign" is a declared null. A magnitude-only score would
    # be indistinguishable from it.
    up_closes, vol = compressed_then_burst(burst=5_000)
    down_closes, _ = compressed_then_burst(burst=-5_000)
    got = scores(panel(("UP", up_closes, vol), ("DOWN", down_closes, vol)))
    assert got["UP"] > 0 > got["DOWN"]
    assert got["UP"] == -got["DOWN"]


# --------------------------------------------- missing is not default -------------------


def test_insufficient_history_yields_no_forecast() -> None:
    closes = [*wobble(40, 100), 105_000]
    volumes = [1_000 + (i % 7) * 60 for i in range(40)] + [80_000]
    assert scores(panel(("AAA", closes, volumes))) == {}


def test_no_volatility_estimate_yields_no_directional_claim() -> None:
    """The sharpest of the three: *direction is DEFINED relative to the forecast.*

    A perfectly still name has no volatility forecast, so "how extraordinary is this move"
    has no denominator. Scoring it zero would be a measured no-position; scoring it at all
    would be dividing by something that does not exist.
    """
    still = [100_000] * 150 + [105_000]
    volumes = [1_000 + (i % 7) * 60 for i in range(150)] + [80_000]
    assert "STILL" not in scores(panel(("STILL", still, volumes)))


def test_a_name_that_is_not_compressed_is_flat_not_absent() -> None:
    # Measured and found un-compressed is a real answer, and it is different from "we could
    # not measure". A flat score says the first; omission would say the second.
    closes = [*wobble(150, 400), 105_000]
    volumes = [1_000 + (i % 7) * 60 for i in range(150)] + [80_000]
    got = scores(panel(("AAA", closes, volumes)))
    assert got["AAA"] == 0


def test_compression_without_expansion_is_flat() -> None:
    closes, _ = compressed_then_burst(burst=5)
    volumes = [1_000 + (i % 7) * 60 for i in range(len(closes) - 1)] + [1_000]
    got = scores(panel(("AAA", closes, volumes)))
    assert got["AAA"] == 0


# --------------------------------------------- the pre-registered domain ----------------


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("compression_window_m", 5),
        ("compression_window_m", 200),
        ("compression_percentile_c0", 1),
        ("compression_percentile_c0", 60),
        ("expansion_threshold_e0_mad", Decimal("0.5")),
        ("expansion_threshold_e0_mad", Decimal(5)),
        ("hold_minutes", 5),
        ("hold_minutes", 200),
    ],
)
def test_a_parameter_outside_the_pre_registered_domain_is_refused(field: str, bad: object) -> None:
    with pytest.raises(ValueError, match=field.split("_")[0]):
        params(**{field: bad})


def test_the_plugin_reads_nothing_beyond_the_decision_bar() -> None:
    closes, volumes = compressed_then_burst()
    frame = panel(("AAA", closes, volumes))
    view = AsOfPanelView(frame, decision_ts=int(frame["close_ts_ns"].max()))  # type: ignore[arg-type]
    compute(view, params(), spec())
    latest = view.max_source_ts()
    assert latest is not None, "the fixture must be visible, or this proves nothing"
    assert latest <= view.decision_ts


def test_a_still_recent_window_yields_no_forecast_even_with_a_loud_history() -> None:
    """Isolates the "no volatility forecast" guard, which nothing was actually testing.

    The perfectly-still fixture elsewhere in this file excludes its name through a DIFFERENT
    guard — with no history volatility at all, the prior-window population is empty too. So
    removing the `recent_vol == 0` check killed nothing. Here the history is loud and only the
    compression window is still, so the empty-population path cannot fire and the guard under
    test is the only thing standing between the alpha and a division by zero.
    """
    closes = wobble(120, 400) + [100_000] * 40
    closes.append(closes[-1] + 5_000)
    volumes = [1_000 + (i % 7) * 60 for i in range(160)] + [80_000]
    assert "AAA" not in scores(panel(("AAA", closes, volumes)))


def test_range_expansion_without_volume_expansion_is_flat() -> None:
    """Isolates the volume leg of the trigger, which nothing was testing either.

    The "compression without expansion" test uses a tiny move, so the RANGE leg already fails
    and the volume leg never gets a say — removing it killed nothing. Here the range expands
    hard and the volume does not move at all.
    """
    closes, _ = compressed_then_burst(burst=5_000)
    volumes = [1_000 + (i % 7) * 60 for i in range(len(closes))]
    got = scores(panel(("AAA", closes, volumes)))
    assert got["AAA"] == 0, "a range burst on ordinary volume is not the spec's trigger"
