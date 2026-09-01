"""Combined-blotter netting  (§10.2, M19).

The ensemble's internal crossing — one pipeline buying what another sells — reduces REALIZED
turnover below the sum of the parts. §10.2: the combined-blotter simulation measures this
netting ratio and re-prices the ensemble's cost line, which shifts each member's optimal
threshold, and S5 iterates that to a fixed point.

    netting ratio = 1 - ensemble external turnover / sum of member turnovers

**The netting window is the whole risk.** Two pipelines cross only if they trade the same
symbol at the same TIME. A buy at 09:20 and a sell at 14:50 do not cross — both orders go to
the market and both pay the cost line. Netting them on paper produces a saving that was never
available, lowers the ensemble's cost line, admits trades that do not clear their real costs,
and every downstream number stays plausible. So the bucket is required with no default: it is
the single most consequential parameter here and nothing should be able to choose it quietly.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pips.selection.netting import BlotterOrder, combine_blotters

MINUTE = 60 * 1_000_000_000
OPEN = 1_772_000_000 * 1_000_000_000  # an arbitrary but fixed epoch instant


def order(
    pipeline: str, symbol: str, minute: int, quantity: int, price: str = "100.00"
) -> BlotterOrder:
    return BlotterOrder(
        pipeline=pipeline,
        symbol=symbol,
        ts_ns=OPEN + minute * MINUTE,
        quantity=quantity,
        price=Decimal(price),
    )


# ------------------------------------------------------------ crossing ----------------


def test_opposing_orders_in_the_same_symbol_and_bucket_cross() -> None:
    orders = [order("F1", "RELIANCE", 0, +100), order("F5", "RELIANCE", 0, -60)]
    report = combine_blotters(orders, bucket_ns=MINUTE)

    assert report.member_turnover == Decimal("16000.00")  # (100 + 60) * 100
    assert report.external_turnover == Decimal("4000.00")  # net +40
    assert report.netting_ratio == pytest.approx(1 - 4000 / 16000)


def test_a_perfect_cross_produces_no_external_order_at_all() -> None:
    orders = [order("F1", "RELIANCE", 0, +100), order("F5", "RELIANCE", 0, -100)]
    report = combine_blotters(orders, bucket_ns=MINUTE)

    assert report.external_turnover == Decimal(0)
    assert report.netting_ratio == pytest.approx(1.0)
    assert report.combined == (), "a netted-to-zero position is not a zero-quantity order"


def test_orders_on_the_same_side_do_not_net() -> None:
    orders = [order("F1", "RELIANCE", 0, +100), order("F5", "RELIANCE", 0, +60)]
    report = combine_blotters(orders, bucket_ns=MINUTE)
    assert report.netting_ratio == pytest.approx(0.0)
    assert report.external_turnover == report.member_turnover


# ------------------------------------------------------------ the netting window ------


def test_orders_in_different_buckets_do_not_cross() -> None:
    """The headline trap. Both orders reach the market and both pay the cost line.

    Netting a 09:20 buy against a 14:50 sell books a saving that was never available. The
    ensemble's cost line drops, trades that do not clear their real costs get admitted, and
    every number downstream stays perfectly plausible.
    """
    orders = [order("F1", "RELIANCE", 0, +100), order("F5", "RELIANCE", 330, -100)]
    report = combine_blotters(orders, bucket_ns=MINUTE)

    assert report.netting_ratio == pytest.approx(0.0)
    assert report.external_turnover == report.member_turnover
    assert len(report.combined) == 2


def test_a_wider_bucket_nets_more_which_is_why_it_cannot_default() -> None:
    # Same orders, two windows. The parameter alone moves the measured saving from nothing to
    # everything, so it is required and stated rather than chosen by the module.
    orders = [order("F1", "RELIANCE", 0, +100), order("F5", "RELIANCE", 3, -100)]
    tight = combine_blotters(orders, bucket_ns=MINUTE)
    wide = combine_blotters(orders, bucket_ns=10 * MINUTE)

    assert tight.netting_ratio == pytest.approx(0.0)
    assert wide.netting_ratio == pytest.approx(1.0)


def test_orders_straddling_a_bucket_boundary_are_not_netted() -> None:
    """Fixed epoch-aligned buckets mean two orders a second apart can land either side.

    That UNDERSTATES netting, which is the conservative direction: the ensemble is charged for
    a crossing it might have got. Stated rather than corrected, because the alternative —
    sliding windows that chase pairs — would report a saving whenever one can be constructed.
    """
    # The boundary is COMPUTED, not assumed. Writing `OPEN + MINUTE - 1` and `OPEN + MINUTE`
    # looks like a straddle and is not: buckets are epoch-aligned and OPEN happens to sit 20s
    # into one, so both of those land in the same bucket and net. The fixture has to find the
    # real boundary or it silently tests the opposite of what it claims.
    boundary = ((OPEN // MINUTE) + 1) * MINUTE
    just_before = BlotterOrder("F1", "RELIANCE", boundary - 1, +100, Decimal("100.00"))
    just_after = BlotterOrder("F5", "RELIANCE", boundary, -100, Decimal("100.00"))
    report = combine_blotters([just_before, just_after], bucket_ns=MINUTE)
    assert report.netting_ratio == pytest.approx(0.0)


def test_a_bucket_is_required_and_must_be_positive() -> None:
    orders = [order("F1", "RELIANCE", 0, +100)]
    for bad in (0, -MINUTE):
        with pytest.raises(ValueError, match="bucket"):
            combine_blotters(orders, bucket_ns=bad)


# ------------------------------------------------------------ what never nets ---------


def test_different_symbols_never_cross() -> None:
    orders = [order("F1", "RELIANCE", 0, +100), order("F5", "TCS", 0, -100)]
    report = combine_blotters(orders, bucket_ns=MINUTE)
    assert report.netting_ratio == pytest.approx(0.0)
    assert len(report.combined) == 2


def test_one_pipeline_crossing_itself_still_counts() -> None:
    # It is a COMBINED blotter: what reaches the market is the net, whoever generated it.
    orders = [order("F1", "RELIANCE", 0, +100), order("F1", "RELIANCE", 0, -40)]
    report = combine_blotters(orders, bucket_ns=MINUTE)
    assert report.external_turnover == Decimal("6000.00")


# ------------------------------------------------------------ the ratio ---------------


def test_the_ratio_is_bounded_by_construction() -> None:
    # |sum(x)| <= sum(|x|), so external can never exceed member turnover. A ratio outside
    # [0, 1] is not a surprising result, it is a bug, and it must not be reportable.
    orders = [
        order("F1", "RELIANCE", m % 4, +100 if m % 3 else -70, price="101.50") for m in range(24)
    ] + [order("F5", "TCS", m % 4, -55 if m % 2 else +80, price="3200.00") for m in range(24)]
    report = combine_blotters(orders, bucket_ns=MINUTE)
    assert 0.0 <= report.netting_ratio <= 1.0


def test_an_empty_blotter_has_no_ratio_rather_than_a_ratio_of_zero() -> None:
    """Nothing traded is not 'nothing crossed'.

    Zero would read as a measured absence of netting and feed a cost re-pricing as though it
    were evidence.
    """
    with pytest.raises(ValueError, match="no turnover"):
        combine_blotters([], bucket_ns=MINUTE)


def test_a_blotter_of_zero_quantities_has_no_ratio() -> None:
    with pytest.raises(ValueError, match="no turnover"):
        combine_blotters([order("F1", "RELIANCE", 0, 0)], bucket_ns=MINUTE)


def test_the_ratio_cannot_be_asked_for() -> None:
    """It is a MEASUREMENT of the blotter, like turnover is an output of the threshold.

    A `blotter_for_netting_ratio` would invert it into 'arrange trades until the saving looks
    good', which is the same error §6.2 refuses about turnover.
    """
    import pips.selection.netting as module

    assert [n for n in dir(module) if "for_ratio" in n or "target_ratio" in n] == []


# ------------------------------------------------------------ shares are integers -----


def test_a_fractional_quantity_is_refused_deliberately() -> None:
    """NSE cash equity trades whole shares, and the refusal has to be the module's own.

    Matching a bare TypeError passes without any check at all: `float * Decimal` raises one by
    accident on the very next line. That is an arithmetic coincidence, not a rule — it would
    vanish the moment turnover moved to float — so the message is asserted, not just the type.
    """
    with pytest.raises(TypeError, match="whole shares"):
        combine_blotters(
            [BlotterOrder("F1", "RELIANCE", OPEN, 100.5, Decimal("100.00"))],  # type: ignore[arg-type]
            bucket_ns=MINUTE,
        )


def test_the_netted_residual_is_priced_at_the_buckets_volume_weighted_price() -> None:
    """Members pay their own prices; the residual is one order at the bucket's VWAP.

    Using either price alone would make the ratio depend on which pipeline is listed first.
    """
    orders = [
        BlotterOrder("F1", "RELIANCE", OPEN, +100, Decimal("100.00")),
        BlotterOrder("F5", "RELIANCE", OPEN, -60, Decimal("110.00")),
    ]
    report = combine_blotters(orders, bucket_ns=MINUTE)
    vwap = (Decimal(100) * Decimal("100.00") + Decimal(60) * Decimal("110.00")) / Decimal(160)
    assert report.external_turnover == Decimal(40) * vwap
    assert report.member_turnover == Decimal("10000.00") + Decimal("6600.00")


def test_the_combined_blotter_is_ordered_deterministically() -> None:
    orders = [
        order("F5", "TCS", 2, -55),
        order("F1", "RELIANCE", 0, +100),
        order("F1", "SBIN", 1, +7),
    ]
    first = combine_blotters(orders, bucket_ns=MINUTE)
    second = combine_blotters(list(reversed(orders)), bucket_ns=MINUTE)
    assert [(c.symbol, c.bucket, c.quantity) for c in first.combined] == [
        (c.symbol, c.bucket, c.quantity) for c in second.combined
    ]


def test_the_report_carries_the_window_that_produced_it() -> None:
    """A netting ratio without its bucket is uninterpretable.

    0.6 over one minute is a real crossing; 0.6 over a whole session is mostly an artefact of
    the window. Anything that stores or compares ratios needs the parameter alongside.
    """
    report = combine_blotters([order("F1", "RELIANCE", 0, +100)], bucket_ns=5 * MINUTE)
    assert report.bucket_ns == 5 * MINUTE


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "blotter-netting" in CHECK_REGISTRY
    resolve_check("blotter-netting")
