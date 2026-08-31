"""Nested walk-forward with purging and embargo  (§6 M15).

M15's Verify is *"the leakage canary dies here; overlap-inflation demo"*, and the canary it
means is not the one in `pips/alphas/canary.py`. That one catches SPATIAL leakage — reading a
field the as-of view forbids. This is TEMPORAL leakage, and it needs no forbidden field at all:

**A training label computed over `[t, t+h]` reaches into the test window whenever `t + h`
lands inside it.** Nothing was read that should not have been; the label simply spans the
boundary. The training and test sets then share actual bars, and a model that memorises its
training labels scores on the test set for free.

That is why the demonstration here is structural rather than statistical. Counting overlapping
label windows is exact, needs no market data, and cannot be argued with: a naive split has
some, a purged split has **zero**. A statistical demonstration would have to argue about how
much inflation is too much; this one does not.

The embargo is the second half. Purging handles labels that reach FORWARD into the test window;
the embargo handles the serial correlation that makes samples immediately AFTER a test window
almost the same observation. §6 M15 fixes its size: `embargo >= horizon + order duration`.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from pips.validation.walk_forward import (
    Fold,
    inner_folds,
    overlapping_label_pairs,
    walk_forward,
)


def folds(**over: object) -> list[Fold]:
    base: dict[str, object] = {
        "n_samples": 400,
        "train_size": 126,
        "test_size": 21,
        "horizon": 5,
        "embargo": 10,
    }
    base.update(over)
    return walk_forward(**base)  # type: ignore[arg-type]


# ------------------------------------------------------------ the canary ---------------


def test_no_training_label_reaches_into_its_test_window() -> None:
    """The canary, stated exactly.

    For every fold and every training sample, the label window `[i, i+h]` must end strictly
    before the test window begins. One overlapping pair is one bar the model saw twice.
    """
    for fold in folds():
        for i in fold.train_indices:
            assert i + fold.horizon < fold.test_start, (
                f"training sample {i} labels through {i + fold.horizon}, inside the test "
                f"window starting {fold.test_start}"
            )


def test_a_purged_split_has_zero_overlapping_label_pairs() -> None:
    for fold in folds():
        assert overlapping_label_pairs(fold) == 0


def test_an_unpurged_split_has_overlapping_pairs_and_this_is_the_demo() -> None:
    """The control, and the whole point.

    Without it, `overlapping_label_pairs == 0` could be a function that always returns zero —
    and every assertion above would hold for a splitter that does no purging at all, because
    a splitter returning empty training sets also has no overlaps.
    """
    unpurged = folds(purge=False)
    assert any(overlapping_label_pairs(f) > 0 for f in unpurged), (
        "an unpurged split MUST leak, or the purged split's zero means nothing"
    )
    assert all(f.train_indices for f in unpurged)


def test_the_number_of_purged_samples_is_exactly_the_horizon() -> None:
    # A label spanning h bars reaches the test window from exactly the last h training
    # samples. Purging more would be arbitrary caution; purging fewer would leak.
    for purged, plain in zip(folds(), folds(purge=False), strict=True):
        assert len(plain.train_indices) - len(purged.train_indices) == purged.horizon


# ------------------------------------------------------------ the embargo --------------


def test_samples_immediately_after_a_test_window_are_embargoed() -> None:
    for fold in folds():
        forbidden = range(fold.test_end, fold.test_end + fold.embargo)
        assert not (set(fold.train_indices) & set(forbidden))


def test_an_embargo_shorter_than_horizon_plus_order_duration_is_refused() -> None:
    # §6 M15 fixes the floor: `embargo >= horizon + order duration`. A shorter embargo is not
    # a tuning choice, it is a violation of the split's own definition.
    with pytest.raises(ValueError, match="embargo"):
        walk_forward(
            n_samples=400, train_size=126, test_size=21, horizon=5, embargo=4, order_duration=3
        )


def test_the_declared_floor_is_the_one_the_spec_names() -> None:
    ok = walk_forward(
        n_samples=400, train_size=126, test_size=21, horizon=5, embargo=8, order_duration=3
    )
    assert ok, "horizon 5 + order duration 3 = 8 must be acceptable"


# ------------------------------------------------------------ the walk -----------------


def test_test_windows_march_forward_and_never_overlap() -> None:
    made = folds()
    assert len(made) >= 2
    for earlier, later in pairwise(made):
        assert earlier.test_end <= later.test_start


def test_training_is_always_strictly_before_testing() -> None:
    for fold in folds():
        assert max(fold.train_indices) < fold.test_start


def test_the_spec_default_geometry_is_what_is_built() -> None:
    fold = folds()[0]
    assert fold.test_end - fold.test_start == 21
    assert fold.horizon == 5


def test_a_dataset_too_short_for_one_fold_yields_none_rather_than_a_short_one() -> None:
    # A truncated fold is a fold with a smaller training set than declared, which quietly
    # changes the experiment. Returning nothing says so.
    assert walk_forward(n_samples=50, train_size=126, test_size=21, horizon=5, embargo=10) == []


def test_the_same_parameters_produce_identical_folds() -> None:
    assert folds() == folds()


# ------------------------------------------------- the nested half ----------------------
# A mutation run found the embargo was decoration: in a forward-only outer walk, training is
# entirely in the past, so "exclude the window after the test block" can never bind and the
# test asserting it passed on an empty intersection. The embargo is real where training data
# exists on BOTH sides of a test block — which is the inner folds, the "nested" in nested
# walk-forward, and the half that was missing.


def test_inner_folds_live_entirely_inside_the_outer_training_window() -> None:
    outer = folds()[0]
    for inner in inner_folds(outer, inner_test_size=21):
        assert set(inner.test_indices) <= set(outer.train_indices), (
            "an inner test block that reaches into the outer test window would tune on the "
            "data the outer fold exists to hold back"
        )
        assert set(inner.train_indices) <= set(outer.train_indices)


def test_an_inner_fold_has_training_data_after_its_test_block() -> None:
    """The precondition that makes the embargo mean anything.

    If every inner fold's training data were also entirely in the past, the embargo would be
    decoration here too and these tests would pass for a splitter that ignores it.
    """
    inners = inner_folds(folds()[0], inner_test_size=21)
    assert any(max(f.train_indices) > f.test_end for f in inners), (
        "no inner fold trains on data after its own test block — the embargo cannot bind and "
        "nothing below tests anything"
    )


def test_the_embargo_window_after_an_inner_test_block_is_excluded() -> None:
    for inner in inner_folds(folds()[0], inner_test_size=21):
        forbidden = set(range(inner.test_end, inner.test_end + inner.embargo))
        assert not (set(inner.train_indices) & forbidden)


def test_inner_folds_are_purged_on_the_leading_side_too() -> None:
    for inner in inner_folds(folds()[0], inner_test_size=21):
        assert overlapping_label_pairs(inner) == 0


def test_every_test_window_stays_inside_the_data() -> None:
    # A fold whose test window runs past the end of the data is a fold scored on samples that
    # do not exist. Nothing else in this file asserted it, and a mutation run said so.
    for fold in folds(n_samples=400):
        assert fold.test_end <= 400
