"""A05 gap continuation and A06 gap reversal -- the session-structure pair (§5 F5, [C-SPEC-01]).

Written **together**, because writing one first is the failure their pre-registration exists to
prevent. §5 F5: *continue/fade separate, never chosen ex post.* If continuation shipped alone
and reversal arrived only after continuation disappointed, the pair would be one selection
wearing two names, and A06's first falsifier — "reject if continuation and reversal rules are
selected ex post by realized sign" — would already be violated by the commit order.

So the load-bearing test here is not that either scores well. It is that on the same panel,
with the same parameters, **no name is simultaneously a continuation and a reversal**. Two
alphas that always disagree are one alpha and a minus sign.

The second theme is A06's `no_event_flag` node, which the spec makes mandatory: *missing event
metadata => EXCLUDE the name, never assume no event.* The corporate-action master now exists
but holds nothing, and **an empty master and a quiet market look identical** unless the code
insists on the difference. So event status is tri-state, `UNKNOWN` excludes, and with no
source wired A06 forecasts nothing at all — loudly, in a test.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import polars as pl

from pips.alphas.spec import AlphaSpec, load_alpha_spec
from pips.alphas.t1._common import EventStatus
from pips.alphas.t1.a05 import A05Params
from pips.alphas.t1.a05 import compute as compute_a05
from pips.alphas.t1.a06 import A06Params
from pips.alphas.t1.a06 import compute as compute_a06
from pips.core.asof import AsOfPanelView

SPEC_DIR = Path("config/search_spaces")
NS = 1_000_000_000
MIN = 60 * NS
# 2026-06-01 09:16 IST as ns; sessions are one day apart.
SESSION_1 = 1_780_285_560_000_000_000
DAY = 24 * 60 * 60 * NS


def spec05() -> AlphaSpec:
    return load_alpha_spec(SPEC_DIR / "A05_gap_continuation.yaml")


def spec06() -> AlphaSpec:
    return load_alpha_spec(SPEC_DIR / "A06_gap_reversal.yaml")


def session(
    symbol: str, start_ts: int, opens: list[int], closes: list[int], volumes: list[int]
) -> list[dict[str, object]]:
    return [
        {
            "close_ts_ns": start_ts + i * MIN,
            "symbol": symbol,
            "open_paise": o,
            "close_paise": c,
            "high_paise": max(o, c),
            "low_paise": min(o, c),
            "volume": v,
        }
        for i, (o, c, v) in enumerate(zip(opens, closes, volumes, strict=True))
    ]


def flat_session(
    symbol: str, start_ts: int, price: int, n: int, volume: int = 1000, wobble: int = 10
) -> list[dict[str, object]]:
    """A session with a little movement, so prior-day volatility is non-zero.

    A perfectly flat prior day gives sigma 0, and the plugins refuse to scale by it — correct,
    but it makes every other assertion in a test vacuous, so fixtures wobble on purpose.
    """
    opens = [price + (i % 2) * wobble for i in range(n)]
    closes = [price + ((i + 1) % 2) * wobble for i in range(n)]
    return session(symbol, start_ts, opens, closes, [volume] * n)


def panel(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows).sort(["close_ts_ns", "symbol"])


def two_day_panel(
    gaps: dict[str, int], opening_volume: dict[str, int] | None = None, n: int = 40
) -> pl.DataFrame:
    """Prior session at 100000 paise for every name; today opens at 100000 + its gap."""
    rows: list[dict[str, object]] = []
    for symbol, gap in gaps.items():
        rows += flat_session(symbol, SESSION_1, 100_000, n)
        vol = (opening_volume or {}).get(symbol, 1_000)
        today = flat_session(symbol, SESSION_1 + DAY, 100_000 + gap, n, volume=vol)
        today[0]["open_paise"] = 100_000 + gap
        rows += today
    return panel(rows)


def view_at_open(frame: pl.DataFrame, observe_minutes: int) -> AsOfPanelView:
    """Decision time `observe_minutes` into the second session."""
    return AsOfPanelView(frame, decision_ts=SESSION_1 + DAY + observe_minutes * MIN)


P05 = A05Params(
    observe_minutes=5,
    hold_minutes=30,
    min_volume_ratio=Decimal("1.5"),
    min_breadth=Decimal("0.6"),
    horizon_ns=30 * MIN,
)
P06 = A06Params(
    observe_minutes=5,
    hold_minutes=30,
    max_volume_ratio=Decimal("1.5"),
    max_breadth=Decimal("0.6"),
    max_range_continuation=Decimal("0.5"),
    horizon_ns=30 * MIN,
)


# ------------------------------------------------- the pair, not the parts --------------


def test_no_name_is_both_a_continuation_and_a_reversal() -> None:
    """A06's null model: *A05 continuation on the same names — the two must not be mirror
    images of one selection.* This is the test that keeps them honest."""
    frame = two_day_panel(
        {"AAA": 5_000, "BBB": -4_000, "CCC": 200, "DDD": 4_500},
        opening_volume={"AAA": 9_000, "BBB": 1_000, "CCC": 1_000, "DDD": 900},
    )
    view = view_at_open(frame, 5)
    clear = {s: EventStatus.CLEAR for s in ("AAA", "BBB", "CCC", "DDD")}

    cont = {f.instrument_id: f.expected_return_bps for f in compute_a05(view, P05, spec05())}
    rev = {
        f.instrument_id: f.expected_return_bps
        for f in compute_a06(view_at_open(frame, 5), P06, spec06(), event_status=clear.get)
    }
    both = {s for s in cont if cont[s] != 0 and rev.get(s, Decimal(0)) != 0}
    assert not both, f"{sorted(both)} are scored by BOTH continuation and reversal"


# ------------------------------------------------------------- A05 ----------------------


def test_an_unconfirmed_gap_is_flat_and_not_reversed() -> None:
    # The spec: "unconfirmed => flat, not a reversed position". A flat score and a reversed
    # one are opposite trades; defaulting to the second would make A05 into A06 by accident.
    frame = two_day_panel({"AAA": 5_000, "BBB": 0, "CCC": 0}, opening_volume={"AAA": 1_000})
    scores = {
        f.instrument_id: f.expected_return_bps
        for f in compute_a05(view_at_open(frame, 5), P05, spec05())
    }
    assert scores["AAA"] == 0


def test_flat_is_reported_not_omitted() -> None:
    """A deliberate flat and an uncomputable name must be distinguishable.

    Emitting nothing for both would collapse "we looked and the answer is no position" into
    "we could not look" — the distinction this project keeps having to re-establish.
    """
    frame = two_day_panel({"AAA": 5_000, "BBB": 0, "CCC": 0}, opening_volume={"AAA": 1_000})
    assert "AAA" in {f.instrument_id for f in compute_a05(view_at_open(frame, 5), P05, spec05())}


def test_a_name_with_no_prior_session_yields_no_forecast() -> None:
    # No prior close means no gap measure at all — which is NOT a flat position.
    rows = (
        flat_session("AAA", SESSION_1 + DAY, 100_000, 40)
        + flat_session("BBB", SESSION_1, 100_000, 40)
        + flat_session("BBB", SESSION_1 + DAY, 100_000, 40)
    )
    scores = {f.instrument_id for f in compute_a05(view_at_open(panel(rows), 5), P05, spec05())}
    assert "AAA" not in scores


def test_a_market_wide_gap_is_not_an_idiosyncratic_one() -> None:
    """The peer-median leg, which is the whole 'idiosyncratic' claim.

    If every name gaps the same way, that is market direction — and A05's third falsifier is
    'reject if it is not distinct from market direction'. Without peer-median removal this
    fixture would score every name strongly, which is the alpha measuring the index.
    """
    frame = two_day_panel(
        {s: 5_000 for s in ("AAA", "BBB", "CCC", "DDD")},
        opening_volume=dict.fromkeys(("AAA", "BBB", "CCC", "DDD"), 9_000),
    )
    scores = [f.expected_return_bps for f in compute_a05(view_at_open(frame, 5), P05, spec05())]
    assert scores and all(s == 0 for s in scores), scores


# ------------------------------------------------------------- A06 ----------------------


def test_with_no_event_source_a06_forecasts_nothing() -> None:
    """The conservative direction, made visible.

    A06's spec: "missing event metadata => EXCLUDE the name, never assume no event", and its
    deferred falsifier says that until the PIT masters carry events, every name is treated as
    flagged. The corporate-action master exists now but holds nothing — so an empty master
    and a market with no events look identical, and only an explicit UNKNOWN keeps them apart.
    """
    frame = two_day_panel({"AAA": 5_000, "BBB": -4_000, "CCC": 100})
    assert compute_a06(view_at_open(frame, 5), P06, spec06()) == []


def test_an_unknown_event_status_excludes_only_that_name() -> None:
    frame = two_day_panel({"AAA": 5_000, "BBB": -4_000, "CCC": 100})
    status = {"AAA": EventStatus.UNKNOWN, "BBB": EventStatus.CLEAR, "CCC": EventStatus.CLEAR}
    got = {
        f.instrument_id
        for f in compute_a06(view_at_open(frame, 5), P06, spec06(), event_status=status.get)
    }
    assert "AAA" not in got and "BBB" in got


def test_a_flagged_name_is_excluded() -> None:
    frame = two_day_panel({"AAA": 5_000, "BBB": -4_000, "CCC": 100})
    status = {"AAA": EventStatus.FLAGGED, "BBB": EventStatus.CLEAR, "CCC": EventStatus.CLEAR}
    got = {
        f.instrument_id
        for f in compute_a06(view_at_open(frame, 5), P06, spec06(), event_status=status.get)
    }
    assert "AAA" not in got


def test_a_weakly_confirmed_gap_reverses_its_sign() -> None:
    frame = two_day_panel(
        {"AAA": 5_000, "BBB": -1_000, "CCC": -1_000, "DDD": -1_000},
        opening_volume=dict.fromkeys(("AAA", "BBB", "CCC", "DDD"), 500),
    )
    clear = dict.fromkeys(("AAA", "BBB", "CCC", "DDD"), EventStatus.CLEAR)
    scores = {
        f.instrument_id: f.expected_return_bps
        for f in compute_a06(view_at_open(frame, 5), P06, spec06(), event_status=clear.get)
    }
    assert scores["AAA"] < 0, "a positive idiosyncratic gap must produce a negative fade score"


def test_a_strongly_confirmed_gap_is_flat_for_a06() -> None:
    # Strong confirmation is A05's territory. A06 going flat there — rather than fading anyway
    # — is what stops the two from partitioning the same names by sign.
    frame = two_day_panel(
        {"AAA": 5_000, "BBB": -1_000, "CCC": -1_000, "DDD": -1_000},
        opening_volume={"AAA": 9_000, "BBB": 500, "CCC": 500, "DDD": 500},
    )
    clear = dict.fromkeys(("AAA", "BBB", "CCC", "DDD"), EventStatus.CLEAR)
    scores = {
        f.instrument_id: f.expected_return_bps
        for f in compute_a06(view_at_open(frame, 5), P06, spec06(), event_status=clear.get)
    }
    assert scores["AAA"] == 0


# ------------------------------------------------------- causality ----------------------


def test_neither_plugin_reads_beyond_the_decision_bar() -> None:
    frame = two_day_panel({"AAA": 5_000, "BBB": -4_000, "CCC": 100})

    a05_view = view_at_open(frame, 5)
    compute_a05(a05_view, P05, spec05())
    a06_view = view_at_open(frame, 5)
    compute_a06(a06_view, P06, spec06(), event_status=lambda _s: EventStatus.CLEAR)

    for view in (a05_view, a06_view):
        latest = view.max_source_ts()
        assert latest is not None, "the fixture must actually be visible, or this proves nothing"
        assert latest <= view.decision_ts


def test_breadth_counts_peers_only_so_a_name_cannot_confirm_itself() -> None:
    """Self-confirmation, which a mutation run showed nothing was catching.

    Including the name in its own breadth puts a floor of 1/n on every reading. With two
    names that floor is 0.5, so a stock whose ONLY peer gaps the other way still reads as
    half-confirmed — confirmed entirely by itself. At the thresholds used elsewhere in this
    file both readings land on the same side of the gate, which is why replacing
    `peers` with `gaps.values()` killed no test.

    Here the threshold sits between them: peers-only gives 0 and is unconfirmed; counting
    itself gives 0.5 and would trade.
    """
    frame = two_day_panel({"AAA": 5_000, "BBB": -5_000}, opening_volume={"AAA": 9_000})
    params = A05Params(
        observe_minutes=5,
        hold_minutes=30,
        min_volume_ratio=Decimal("1.5"),
        min_breadth=Decimal("0.4"),
        horizon_ns=30 * MIN,
    )
    scores = {
        f.instrument_id: f.expected_return_bps
        for f in compute_a05(view_at_open(frame, 5), params, spec05())
    }
    assert scores["AAA"] == 0, (
        "AAA's only peer gapped the other way — breadth is 0, and a name must not confirm "
        f"itself into a position; got {scores['AAA']}"
    )


def test_the_smoke_report_derives_its_plugin_list_from_the_package() -> None:
    """The report's headline claim is *which alphas can actually run*.

    It used to be a hardcoded set, which is the drift already caught twice here — the
    registry's DDL against its model, and the deploy rail's service list against compose. A
    stale list makes the claim wrong in the flattering direction: specs reported as runnable
    that have no plugin, or plugins that exist and go unmentioned.
    """
    import importlib

    from pips.search.s1 import specs_with_plugins

    derived = specs_with_plugins()
    assert {"A05", "A06"} <= derived
    for spec_id in derived:
        module = importlib.import_module(f"pips.alphas.t1.{spec_id.lower()}")
        assert hasattr(module, "compute"), f"{spec_id} is listed but exports no compute()"
