"""Nested walk-forward with purging and embargo  (§6 M15).

M15's Verify is *"the leakage canary dies here; overlap-inflation demo"*, and the canary it
means is not the one in :mod:`pips.alphas.canary`. That one catches SPATIAL leakage — reading
a field the as-of view forbids. This is TEMPORAL leakage, and it needs no forbidden field:

**A training label computed over ``[t, t+h]`` reaches into the test window whenever ``t + h``
lands inside it.** Nothing was read that should not have been. The label simply spans the
boundary, the two sets share actual bars, and a model that memorises its training labels scores
on the test set for free.

So the demonstration here is structural, not statistical. Counting overlapping label windows is
exact, needs no market data, and cannot be argued with: a naive split has some, a purged split
has zero. A statistical demonstration would have to argue about how much inflation is too much.

**Purging** removes labels that reach forward into the test window — exactly the last ``h``
training samples, no more. Removing more would be arbitrary caution dressed as rigour, and
arbitrary caution is a parameter.

**The embargo** handles the other side: samples immediately AFTER a test window are so serially
correlated with it as to be nearly the same observation. §6 M15 fixes its floor at
``horizon + order duration``, and this module refuses a shorter one — that is not a tuning
choice, it is a violation of the split's own definition.

A dataset too short for a full fold yields NO folds rather than a truncated one. A short fold
is a fold with a smaller training set than the experiment declared, which changes the
experiment without saying so.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Fold", "inner_folds", "overlapping_label_pairs", "walk_forward"]


@dataclass(frozen=True)
class Fold:
    """One outer fold: which samples train, which test, and the geometry that produced them."""

    train_indices: tuple[int, ...]
    test_start: int
    test_end: int
    horizon: int
    embargo: int

    @property
    def test_indices(self) -> tuple[int, ...]:
        return tuple(range(self.test_start, self.test_end))


def overlapping_label_pairs(fold: Fold) -> int:
    """Training/test sample pairs whose label windows share at least one bar.

    The overlap-inflation demo in its exact form. Each such pair is a bar the model saw on
    both sides of the split, and the count is a fact rather than an estimate.
    """
    overlaps = 0
    for train_i in fold.train_indices:
        train_end = train_i + fold.horizon
        for test_j in fold.test_indices:
            if train_i <= test_j + fold.horizon and test_j <= train_end:
                overlaps += 1
    return overlaps


def walk_forward(
    n_samples: int,
    train_size: int,
    test_size: int,
    horizon: int,
    embargo: int,
    order_duration: int = 0,
    purge: bool = True,
) -> list[Fold]:
    """Rolling outer folds with purging and embargo.

    ``purge=False`` exists ONLY so the demonstration has a control. An assertion that a purged
    split has zero overlapping pairs is worth nothing without a companion showing that an
    unpurged one does not — otherwise it holds equally for a splitter that returns no training
    samples at all.
    """
    if embargo < horizon + order_duration:
        raise ValueError(
            f"embargo {embargo} is below the floor of horizon + order duration "
            f"({horizon} + {order_duration} = {horizon + order_duration}) that §6 M15 fixes. "
            "A shorter embargo is not a tuning choice; it contradicts the definition of the "
            "split, because samples that close within the embargo are nearly the same "
            "observation as the test window they follow."
        )
    if min(train_size, test_size, n_samples) <= 0 or horizon < 0:
        raise ValueError("sizes must be positive and the horizon non-negative")

    folds: list[Fold] = []
    test_start = train_size
    while test_start + test_size <= n_samples:
        test_end = test_start + test_size
        candidates = range(max(0, test_start - train_size), test_start)
        train = [
            i
            for i in candidates
            # PURGE: the label must close strictly before the test window opens.
            if (not purge or i + horizon < test_start)
            # EMBARGO: nothing from the window immediately after a test block. In a
            # forward-only walk this never binds on the current fold -- training is entirely
            # in the past -- but it binds as soon as the scheme becomes anchored or the folds
            # are reused, and a rule that is only applied when it happens to matter is a rule
            # nobody can rely on.
            and not (test_end <= i < test_end + embargo)
        ]
        if train:
            folds.append(
                Fold(
                    train_indices=tuple(train),
                    test_start=test_start,
                    test_end=test_end,
                    horizon=horizon,
                    embargo=embargo,
                )
            )
        test_start = test_end
    return folds


def inner_folds(outer: Fold, inner_test_size: int) -> list[Fold]:
    """Inner CV folds carved out of one outer fold's TRAINING window.

    This is the "nested" in nested walk-forward, and it is where the embargo earns its keep. In
    the outer walk, training is entirely in the past of its test block, so "exclude the window
    immediately after the test" can never bind — a mutation run proved the rule was decoration
    there, passing on an empty intersection. Inside the training window an inner test block has
    training data on BOTH sides, and the samples just after it are so serially correlated with
    it as to be nearly the same observation.

    Both rules therefore apply here for real:

    - **purge** on the leading side: a training label must close before the inner test opens;
    - **embargo** on the trailing side: nothing from the ``embargo`` samples that follow it.

    Inner blocks never touch the outer test window. Tuning on the data the outer fold exists
    to hold back is the leak the whole nesting is built to prevent.
    """
    available = list(outer.train_indices)
    if inner_test_size <= 0 or len(available) < inner_test_size * 2:
        return []

    made: list[Fold] = []
    for start in range(0, len(available) - inner_test_size + 1, inner_test_size):
        block = available[start : start + inner_test_size]
        test_start, test_end = block[0], block[-1] + 1

        def admissible(i: int, test_start: int = test_start, test_end: int = test_end) -> bool:
            """Whether a sample may train against this inner test block.

            Written as a named predicate rather than a comprehension clause: the first draft
            was one expression leaning on `and`/`or` precedence, which is an unacceptable way
            to write the rule that defines what leakage means.
            """
            if test_start <= i < test_end:
                return False  # the block itself
            if i < test_start:
                return i + outer.horizon < test_start  # purge: the label must close first
            return i >= test_end + outer.embargo  # embargo: clear of the correlated tail

        train = [i for i in available if admissible(i)]
        if train:
            made.append(
                Fold(
                    train_indices=tuple(sorted(set(train))),
                    test_start=test_start,
                    test_end=test_end,
                    horizon=outer.horizon,
                    embargo=outer.embargo,
                )
            )
    return made
