"""Hansen's SPA test  (§6 M18).

SPA asks whether the BEST model in a set genuinely beats a benchmark, given that you looked at
all of them. Its predecessor, White's Reality Check, answers the same question and answers it
too conservatively — and the reason is worth stating precisely, because it is the whole content
of "Hansen recentering".

**The Reality Check lets hopeless models inflate the null.** It builds the null distribution by
recentering every model on its own sample mean, so a model that lost badly still contributes a
draw to the maximum. Add enough irrelevant bad models and the null's maximum drifts upward, the
p-value rises, and a genuinely superior model stops being detectable — **you fail to reject
because of models nobody would ever have traded.**

Hansen's fix: a model whose sample mean is far enough below zero cannot plausibly be the best,
so it is recentered to zero rather than to its mean, and stops contributing.

So the decisive test is not "does SPA find a good model" — the Reality Check does that too. It
is **whether padding the set with hopeless models moves the p-value.** Under SPA it should
barely move; under the Reality Check it should climb. Both recenterings are implemented so the
claim can be tested rather than asserted.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pips.validation.spa import spa_test


# COPRIME MULTIPLIERS. My first fixtures used `(t * 7) % 21`, where 7 divides 21, so the
# sequence cycles through THREE values and the "noise" had a mean of +0.003 with a
# t-statistic of 7.5. Not noise at all, and the noise-only control passed for the wrong
# reason. 37 and 101 are coprime, so the cycle covers every residue and the means land at
# ~2e-5.
def noise_model(seed: int, n: int = 200) -> list[Decimal]:
    """No edge over the benchmark: differentials centred on zero (mean ~2e-5)."""
    return [Decimal(((t * 37 + seed * 53) % 101) - 50) / Decimal(2000) for t in range(n)]


def good_model(edge: str = "0.0010", n: int = 200) -> list[Decimal]:
    """A genuine but MARGINAL edge — significant on its own, and only just.

    The magnitude matters. With a large edge the test statistic outruns anything the bootstrap
    can produce, both recenterings return p = 0, and the comparison between them shows
    nothing. The interesting behaviour lives where a result is close to its threshold, which
    is also where it lives in practice.
    """
    return [Decimal(edge) + Decimal(((t * 37) % 101) - 50) / Decimal(2000) for t in range(n)]


def hopeless_model(seed: int, n: int = 200) -> list[Decimal]:
    """Loses to the benchmark by a mile, every period. Nobody would trade it."""
    return [
        Decimal("-0.05") + Decimal(((t * 37 + seed * 53) % 101) - 50) / Decimal(4000)
        for t in range(n)
    ]


def candidates(n_noise: int = 4) -> dict[str, list[Decimal]]:
    return {f"noise{i}": noise_model(i) for i in range(n_noise)}


# ------------------------------------------------------------ the claim ----------------


def test_a_genuinely_superior_model_is_detected() -> None:
    models = {**candidates(), "GOOD": good_model()}
    result = spa_test(models, n_bootstrap=400, block_length=10, seed=11)
    assert result.p_value < 0.05, result.describe()
    assert result.best_model == "GOOD"


def test_a_set_of_noise_is_not_detected() -> None:
    # The control. Without it, a low p-value could be what this test always returns.
    result = spa_test(candidates(), n_bootstrap=400, block_length=10, seed=5)
    assert result.p_value > 0.10, result.describe()


# --------------------------------------- the thing recentering is FOR -------------------


def test_padding_with_hopeless_models_barely_moves_the_spa_p_value() -> None:
    """The decisive test, and the only one that distinguishes SPA from the Reality Check.

    Adding models that lose by a mile changes nothing about whether GOOD is superior. Under
    Hansen recentering they are pushed to zero and stop contributing to the null; under the
    Reality Check they keep their terrible means, drag the null's maximum around, and the
    p-value drifts.
    """
    lean = {**candidates(), "GOOD": good_model()}
    padded = {**lean, **{f"hopeless{i}": hopeless_model(i) for i in range(12)}}

    spa_lean = spa_test(lean, n_bootstrap=400, block_length=10, seed=11)
    spa_padded = spa_test(padded, n_bootstrap=400, block_length=10, seed=11)
    assert spa_lean.p_value < 0.05, "the lean set must be significant, or there is nothing to lose"
    assert spa_padded.p_value == spa_lean.p_value, (
        f"SPA moved from {spa_lean.p_value} to {spa_padded.p_value} on models nobody would "
        "trade — the recentering is not doing its job"
    )
    assert spa_padded.p_value < 0.05, "and the finding survives the padding"


def test_the_reality_check_is_the_one_that_drifts() -> None:
    """The comparison that makes the claim above meaningful.

    Without this, "SPA barely moves" could be true of an implementation where NOTHING moves —
    including one that ignores the extra models entirely for the wrong reason.
    """
    lean = {**candidates(), "GOOD": good_model()}
    padded = {**lean, **{f"hopeless{i}": hopeless_model(i) for i in range(12)}}

    rc_lean = spa_test(lean, n_bootstrap=400, block_length=10, seed=11, recentering="reality-check")
    rc_padded = spa_test(
        padded, n_bootstrap=400, block_length=10, seed=11, recentering="reality-check"
    )
    assert rc_padded.p_value > rc_lean.p_value, (
        "the Reality Check must become MORE conservative as hopeless models are added — "
        f"got {rc_lean.p_value} -> {rc_padded.p_value}"
    )
    # The concrete consequence, not merely a direction: 0.040 -> 0.128 crosses the threshold,
    # so twelve models nobody would trade turn a significant result into a non-significant one.
    assert rc_lean.p_value < 0.05 < rc_padded.p_value, (
        f"the padding must cross the threshold to make the point: "
        f"{rc_lean.p_value} -> {rc_padded.p_value}"
    )


def test_the_recentering_reports_how_many_models_it_excluded() -> None:
    padded = {
        **candidates(),
        "GOOD": good_model(),
        **{f"hopeless{i}": hopeless_model(i) for i in range(12)},
    }
    result = spa_test(padded, n_bootstrap=400, block_length=10, seed=11)
    assert result.recentered_to_zero >= 12, (
        "every hopeless model should be pushed to zero, and the count is what makes that "
        "visible rather than implied"
    )


# ------------------------------------------------------------ shape --------------------


def test_the_result_is_reproducible() -> None:
    models = {**candidates(), "GOOD": good_model()}
    a = spa_test(models, n_bootstrap=100, block_length=10, seed=3)
    b = spa_test(models, n_bootstrap=100, block_length=10, seed=3)
    assert a == b


def test_an_empty_model_set_is_refused() -> None:
    with pytest.raises(ValueError, match="no models"):
        spa_test({}, n_bootstrap=100, block_length=10, seed=1)


def test_models_of_unequal_length_are_refused() -> None:
    ragged = candidates()
    ragged["noise0"] = ragged["noise0"][:-3]
    with pytest.raises(ValueError, match="same length"):
        spa_test(ragged, n_bootstrap=100, block_length=10, seed=1)


def test_an_unknown_recentering_is_refused() -> None:
    # `type: ignore` on purpose: the Literal keeps this out of production code, and the
    # runtime guard is what protects a caller reading a recentering name from a config file,
    # where no type checker is watching.
    with pytest.raises(ValueError, match="recentering"):
        spa_test(
            candidates(),
            n_bootstrap=100,
            block_length=10,
            seed=1,
            recentering="magic",  # type: ignore[arg-type]
        )


def test_too_few_bootstrap_resamples_is_refused() -> None:
    # A p-value from ten resamples has a resolution of 0.1 and reads like a measurement.
    with pytest.raises(ValueError, match="bootstrap"):
        spa_test(candidates(), n_bootstrap=5, block_length=10, seed=1)


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "spa-test" in CHECK_REGISTRY
    resolve_check("spa-test")


def borderline_model(n: int = 200) -> list[Decimal]:
    """Mean about -1.4 standard errors: BETWEEN the two candidate thresholds.

    Hansen's threshold at n=200 is -1.826 standard errors (from the law of the iterated
    logarithm). A model at -1.4 sits inside it and must NOT be recentered; under a hard-coded
    factor of 1.0 the threshold moves to -1.0 and it would be. Every other fixture here is far
    outside both, which is why a mutation replacing the rate with a constant survived.
    """
    return [Decimal("-0.00145") + Decimal(((t * 37) % 101) - 50) / Decimal(2000) for t in range(n)]


def test_the_recentering_threshold_follows_the_iterated_logarithm() -> None:
    models = {**candidates(), "GOOD": good_model(), "BORDERLINE": borderline_model()}
    result = spa_test(models, n_bootstrap=400, block_length=10, seed=11)
    assert result.recentered_to_zero == 0, (
        "at -1.4 standard errors the borderline model is inside Hansen's -1.826 threshold and "
        "must survive; a constant factor of 1.0 would zero it"
    )


def test_a_clearly_hopeless_model_is_still_recentered() -> None:
    # The control for the test above: if nothing were ever recentered, that test would pass
    # for a threshold of negative infinity.
    models = {**candidates(), "GOOD": good_model(), "HOPELESS": hopeless_model(0)}
    assert spa_test(models, n_bootstrap=400, block_length=10, seed=11).recentered_to_zero == 1


def test_a_set_where_nothing_beats_the_benchmark_has_a_zero_statistic() -> None:
    """T_SPA is defined as max(0, ...) and the floor is not cosmetic.

    The null is "no model beats the benchmark". When none does, the evidence against that null
    is exactly nothing, and the statistic is 0 — not the least-bad model's negative t. Both
    give a large p-value, which is why a mutation removing the floor survived; the definition
    is what is being asserted here.
    """
    all_losers = {f"bad{i}": hopeless_model(i) for i in range(4)}
    result = spa_test(all_losers, n_bootstrap=400, block_length=10, seed=11)
    assert result.statistic == 0.0
    assert result.p_value > 0.5
