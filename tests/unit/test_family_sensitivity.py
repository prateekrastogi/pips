"""Parameter-family sensitivity  (§6 M16, A02's falsifier).

A02 pre-registered *"Reject if only one lookback works"* and nothing could evaluate it.

The claim behind it: a real effect shows up across a predeclared family of parameter values,
not at one. A02's plugin already refuses a single-lookback configuration at construction and
averages the declared lookbacks rather than picking the best — but that is a guard against
*searching*, and it says nothing about whether the result survives when you look at each value
on its own. This is that check.

Three design choices:

**More than one value must work.** That is what the falsifier says, exactly. Zero working and
one working are both failures, and they are reported differently, because "nothing worked" and
"one thing worked" lead somewhere different.

**Contiguity is REPORTED, not required.** If 5 and 40 clear the bar while 10 and 20 do not,
that is a suspicious shape — a real effect is usually smooth in its own parameter, which is the
argument plateau-centroid makes for 2D surfaces. But A02 pre-registered "only one works", not
"the working set must be contiguous", and quietly holding an alpha to a stricter bar than it
registered is changing the test after the fact. So the check reports the gap and does not fail
on it.

**Values must come from the declared family.** Scoring a value nobody pre-registered is the
same error `beats-declared-null` refuses: evaluating against something chosen afterwards.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pips.validation.family_sensitivity import family_sensitivity

FAMILY = (5, 10, 20, 40)
BAR = Decimal("0.5")


def scores(**by_value: float) -> dict[int, Decimal]:
    return {int(k.lstrip("v")): Decimal(str(s)) for k, s in by_value.items()}


# ------------------------------------------------------------ the claim ----------------


def test_an_effect_across_several_values_survives() -> None:
    verdict = family_sensitivity(FAMILY, scores(v5=0.8, v10=0.9, v20=0.7, v40=0.2), BAR)
    assert verdict.survives
    assert verdict.working == (5, 10, 20)


def test_an_effect_at_exactly_one_value_is_rejected() -> None:
    """The falsifier, word for word.

    One lookback clearing the bar while the rest fail is a single-parameter artefact, and
    averaging the family — which A02's plugin does — hides it behind a number that looks fine.
    """
    verdict = family_sensitivity(FAMILY, scores(v5=0.1, v10=0.9, v20=0.1, v40=0.1), BAR)
    assert not verdict.survives
    assert verdict.working == (10,)


def test_nothing_working_is_reported_differently_from_one_thing_working() -> None:
    # "Nothing worked" and "one thing worked" lead somewhere different: the first says the
    # alpha is absent, the second says it may be an artefact. A single boolean loses that.
    none = family_sensitivity(FAMILY, scores(v5=0.1, v10=0.1, v20=0.1, v40=0.1), BAR)
    one = family_sensitivity(FAMILY, scores(v5=0.1, v10=0.9, v20=0.1, v40=0.1), BAR)
    assert none.working == () and one.working == (10,)
    assert not none.survives and not one.survives
    assert none.describe() != one.describe()


def test_two_values_is_enough_because_that_is_what_was_registered() -> None:
    # Not three, not a majority. A02 registered "only one works" as the rejection condition,
    # and raising the bar afterwards is changing the test.
    verdict = family_sensitivity(FAMILY, scores(v5=0.1, v10=0.9, v20=0.9, v40=0.1), BAR)
    assert verdict.survives


# ------------------------------------------------------------ contiguity ---------------


def test_a_gap_in_the_working_set_is_reported_but_does_not_fail() -> None:
    """5 and 40 work, 10 and 20 do not — a suspicious shape, and not a registered rejection.

    Reporting it surfaces the signal; failing on it would hold A02 to a bar it never
    registered, which is the ex-post tightening this project refuses in the other direction.
    """
    verdict = family_sensitivity(FAMILY, scores(v5=0.9, v10=0.1, v20=0.1, v40=0.9), BAR)
    assert verdict.survives, "two values work, which is what the falsifier asks"
    assert not verdict.contiguous
    assert "not contiguous" in verdict.describe()


def test_a_contiguous_working_set_says_so() -> None:
    verdict = family_sensitivity(FAMILY, scores(v5=0.1, v10=0.9, v20=0.9, v40=0.1), BAR)
    assert verdict.contiguous


# ------------------------------------------------------------ the refusals -------------


def test_a_value_outside_the_declared_family_is_refused() -> None:
    with pytest.raises(ValueError, match="not in the declared family"):
        family_sensitivity(FAMILY, {**scores(v5=0.9, v10=0.9), 7: Decimal("0.9")}, BAR)


def test_a_declared_value_with_no_score_is_refused() -> None:
    """A family evaluated in part is a smaller family reported as the whole one.

    If 40 was declared and never run, "three of four work" is not a fact about the family
    that was registered.
    """
    with pytest.raises(ValueError, match="no score"):
        family_sensitivity(FAMILY, scores(v5=0.9, v10=0.9, v20=0.9), BAR)


def test_a_family_of_one_cannot_be_tested() -> None:
    verdict = family_sensitivity((5,), scores(v5=0.9), BAR)
    assert verdict.testable is False
    assert verdict.survives is False, "not testable is not a pass"


def test_an_empty_family_is_refused() -> None:
    with pytest.raises(ValueError, match="no declared"):
        family_sensitivity((), {}, BAR)


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "family-sensitivity" in CHECK_REGISTRY
    resolve_check("family-sensitivity")
