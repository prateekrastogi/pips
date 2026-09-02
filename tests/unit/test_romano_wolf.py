"""Romano-Wolf stepdown  (§6 M18, "final survivors").

The last gate before a config is called a survivor, and the question it answers is: **of the
models that look good, which ones are we willing to claim — controlling the chance that ANY of
them is a false positive?**

Bonferroni answers it by dividing alpha by the number of tests, which is correct and wasteful:
it ignores that the test statistics are correlated, and on correlated strategies it throws away
most of the power. Romano-Wolf uses the bootstrap JOINT distribution instead, so correlation is
accounted for rather than assumed away.

**The stepdown is where the power comes from.** The first pass compares every statistic against
the (1-alpha) quantile of the maximum across ALL hypotheses. Having rejected some, the second
pass recomputes that maximum over only the SURVIVORS — a smaller maximum, hence a lower
threshold, hence rejections that the first pass could not make. Repeat until nothing new falls.

So the single-step version is implemented alongside, for the same reason the Reality Check sits
beside SPA: a claim that stepping down buys power is worth making only if the version that does
not step down can be run next to it.

**And the size test is the one that matters.** A procedure that rejects everything has
excellent power. §6 M18's Verify asks for Monte-Carlo size, so under a global null the family-
wise error rate must stay near alpha — not merely "some rejections happen".
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pips.validation.romano_wolf import romano_wolf


def noise(seed: int, n: int = 120) -> list[Decimal]:
    """Zero-mean. Coprime multipliers, because `(a·t) % m` cycles through only m/gcd(a,m)
    values and a shared factor makes the "noise" a three-level staircase with a real mean."""
    return [Decimal(((t * 37 + seed * 53) % 101) - 50) / Decimal(2000) for t in range(n)]


def with_edge(edge: str, seed: int, n: int = 120) -> list[Decimal]:
    return [Decimal(edge) + x for x in noise(seed, n)]


# ------------------------------------------------------------ the stepdown -------------


def test_stepdown_never_rejects_fewer_than_single_step() -> None:
    """The guarantee. Stepping down can only ever lower a threshold, never raise one."""
    models = {
        "strong": with_edge("0.006", 1),
        "medium": with_edge("0.003", 2),
        "weak": with_edge("0.0015", 3),
        **{f"noise{i}": noise(10 + i) for i in range(4)},
    }
    stepped = romano_wolf(models, alpha=0.10, n_bootstrap=300, block_length=8, seed=5)
    single = romano_wolf(
        models, alpha=0.10, n_bootstrap=300, block_length=8, seed=5, stepdown=False
    )
    assert set(single.rejected) <= set(stepped.rejected)


def test_stepping_down_buys_at_least_one_extra_rejection() -> None:
    """The claim, demonstrated rather than asserted.

    Without a case where it strictly wins, "never fewer" is satisfied by a stepdown that does
    nothing at all — which is exactly what a broken loop would look like.
    """
    models = {
        "strong": with_edge("0.008", 1),
        "medium": with_edge("0.004", 2),
        "borderline": with_edge("0.0012", 3),
        **{f"noise{i}": noise(10 + i) for i in range(4)},
    }
    stepped = romano_wolf(models, alpha=0.10, n_bootstrap=400, block_length=8, seed=5)
    single = romano_wolf(
        models, alpha=0.10, n_bootstrap=400, block_length=8, seed=5, stepdown=False
    )
    assert len(stepped.rejected) > len(single.rejected), (
        f"stepdown {sorted(stepped.rejected)} vs single-step {sorted(single.rejected)}"
    )
    # Concretely: 'borderline' has a statistic of 0.944. The first threshold is 1.004, so
    # single-step cannot reach it; after 'strong' and 'medium' fall the bar drops to 0.924 and
    # it does. That is the stepdown, in one model.
    assert "borderline" in stepped.rejected
    assert "borderline" not in single.rejected


def test_the_threshold_falls_at_each_step() -> None:
    # The mechanism, visible: each round's maximum is taken over fewer hypotheses.
    models = {
        "strong": with_edge("0.008", 1),
        "medium": with_edge("0.004", 2),
        "borderline": with_edge("0.0012", 3),
        **{f"noise{i}": noise(10 + i) for i in range(4)},
    }
    result = romano_wolf(models, alpha=0.10, n_bootstrap=400, block_length=8, seed=5)
    # `list(...)`: thresholds is a tuple and `sorted` returns a list, so the bare comparison
    # was always False — my bug, not the procedure's.
    assert len(result.thresholds) >= 2, "at least two rounds, or there is no stepdown to see"
    assert list(result.thresholds) == sorted(result.thresholds, reverse=True)
    # Element-wise rather than tuple-vs-tuple: mypy rightly objects that a tuple of floats and
    # a tuple of approx objects can never be equal by type.
    for got, expected in zip(result.thresholds, (1.0036, 0.9241, 0.8260), strict=True):
        assert got == pytest.approx(expected, abs=1e-3), (
            "each round takes its maximum over fewer hypotheses, so the bar drops: "
            f"{[round(t, 4) for t in result.thresholds]}"
        )


# ------------------------------------------------------------ size ---------------------


def test_the_family_wise_error_rate_is_controlled_under_a_global_null() -> None:
    """§6 M18's Monte-Carlo size test, and the one that matters.

    A procedure that rejects everything has excellent power. Under a global null — every model
    genuinely worthless — the chance of ANY rejection must stay near alpha.

    The comparison is against testing each hypothesis at alpha independently, which on five
    models gives a family-wise rate of about 1 - 0.9^5 = 0.41. Forty replications cannot pin
    0.10 precisely, and this does not pretend to: it asserts the rate is far below the
    uncontrolled one, which is what distinguishes a procedure that controls FWER from one that
    does not.
    """
    rejections = 0
    replications = 40
    for r in range(replications):
        models = {f"m{i}": noise(1000 * r + i) for i in range(5)}
        result = romano_wolf(models, alpha=0.10, n_bootstrap=150, block_length=8, seed=r)
        if result.rejected:
            rejections += 1
    rate = rejections / replications
    assert rate < 0.25, (
        f"family-wise rejection rate {rate} under a global null; uncontrolled testing at "
        "alpha=0.10 across 5 models would give about 0.41"
    )


def test_a_genuinely_strong_model_is_still_rejected() -> None:
    # The power control. Without it, FWER control is trivially achieved by rejecting nothing.
    models = {"strong": with_edge("0.010", 1), **{f"noise{i}": noise(10 + i) for i in range(4)}}
    assert (
        "strong"
        in romano_wolf(models, alpha=0.10, n_bootstrap=300, block_length=8, seed=5).rejected
    )


# ------------------------------------------------------------ shape --------------------


def test_the_procedure_terminates_on_all_significant_models() -> None:
    # Every hypothesis rejected means the surviving set empties; the loop must stop there
    # rather than taking a maximum over nothing.
    models = {f"strong{i}": with_edge("0.02", i) for i in range(4)}
    result = romano_wolf(models, alpha=0.10, n_bootstrap=200, block_length=8, seed=5)
    assert set(result.rejected) == set(models)


def test_the_result_is_reproducible() -> None:
    models = {"a": with_edge("0.005", 1), "b": noise(2)}
    first = romano_wolf(models, alpha=0.10, n_bootstrap=200, block_length=8, seed=3)
    assert first == romano_wolf(models, alpha=0.10, n_bootstrap=200, block_length=8, seed=3)


def test_an_empty_model_set_is_refused() -> None:
    with pytest.raises(ValueError, match="no models"):
        romano_wolf({}, alpha=0.10, n_bootstrap=200, block_length=8, seed=1)


def test_an_alpha_outside_the_open_interval_is_refused() -> None:
    for bad in (0.0, 1.0, -0.1):
        with pytest.raises(ValueError, match="alpha"):
            romano_wolf({"a": noise(1)}, alpha=bad, n_bootstrap=200, block_length=8, seed=1)


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "romano-wolf" in CHECK_REGISTRY
    resolve_check("romano-wolf")


def test_the_loop_cannot_run_more_rounds_than_there_are_hypotheses() -> None:
    """Termination is proved, not assumed.

    Each round either rejects at least one hypothesis or breaks, so the round count cannot
    exceed the family size. That was true but implicit — and a mutation removing
    `surviving -= newly` turned it into an INFINITE LOOP that hung a ten-minute test run
    rather than failing. A bound makes the same mutation fail in a second, and a procedure
    that cannot terminate is not a procedure.
    """
    models = {f"strong{i}": with_edge("0.02", i) for i in range(4)}
    result = romano_wolf(models, alpha=0.10, n_bootstrap=200, block_length=8, seed=5)
    assert result.rounds <= len(models) + 1


# ------------------------------------------------ per-hypothesis adjusted p-values -----


def test_every_hypothesis_gets_an_adjusted_p_value() -> None:
    """Why this exists: `stability.spa_p` is a PER-CANDIDATE dossier field, and neither
    `spa_test` nor the reject/no-reject verdict here can fill it.

    `spa_test` returns one family-wise p-value, earned by the BEST model. Writing it into every
    candidate's dossier would hand candidate five the evidence candidate one produced — the
    flattering direction, and for every candidate but one. The stepdown's adjusted p-value is
    the per-hypothesis quantity that is actually defensible.
    """
    models = {
        "strong": with_edge("0.004", 1),
        "mild": with_edge("0.0015", 2),
        "flat": noise(3),
    }
    result = romano_wolf(models, alpha=0.10, n_bootstrap=200, block_length=5, seed=11)

    assert set(result.adjusted_p) == set(models)
    assert all(0.0 <= p <= 1.0 for p in result.adjusted_p.values())


def test_the_adjusted_p_agrees_with_the_rejection_set() -> None:
    """Two answers to one question must not disagree.

    A reader who sees `rejected` and a p-value above alpha beside it has no way to tell which
    is wrong, and the p-value is the one they will quote.
    """
    models = {
        "strong": with_edge("0.004", 1),
        "mild": with_edge("0.0015", 2),
        "flat": noise(3),
    }
    for alpha in (0.05, 0.10, 0.20):
        result = romano_wolf(models, alpha=alpha, n_bootstrap=200, block_length=5, seed=11)
        by_p = {k for k, p in result.adjusted_p.items() if p <= alpha}
        assert by_p == set(result.rejected), (alpha, result.adjusted_p, result.rejected)


def test_the_adjusted_p_never_falls_as_the_stepdown_proceeds() -> None:
    """Monotone by construction: a hypothesis rejected in a later round cannot carry stronger
    evidence than one rejected earlier, whatever the raw bootstrap frequency says.

    Without the running maximum the later rounds' smaller surviving set produces smaller raw
    p-values, and a weak model rejected last would print a better number than the strong one
    rejected first.
    """
    models = {
        "strong": with_edge("0.004", 1),
        "mild": with_edge("0.0015", 2),
        "weak": with_edge("0.0008", 4),
        "flat": noise(3),
    }
    result = romano_wolf(models, alpha=0.20, n_bootstrap=200, block_length=5, seed=11)

    # NOT read off `rejected`: that tuple is alphabetical, not rejection order. The substantive
    # claim is monotonicity in the STATISTIC — a stronger model is rejected no later, so its
    # adjusted p is no larger, and the running maximum is what guarantees it across rounds.
    by_statistic = sorted(result.statistics, key=lambda k: -result.statistics[k])
    ladder = [result.adjusted_p[name] for name in by_statistic]
    assert ladder == sorted(ladder), (by_statistic, result.adjusted_p, result.statistics)


def test_a_stronger_model_never_gets_a_worse_adjusted_p() -> None:
    models = {
        "strong": with_edge("0.004", 1),
        "flat": noise(3),
    }
    result = romano_wolf(models, alpha=0.10, n_bootstrap=200, block_length=5, seed=11)
    assert result.adjusted_p["strong"] <= result.adjusted_p["flat"]


def test_the_adjusted_p_is_reproducible() -> None:
    models = {"a": with_edge("0.003", 1), "b": noise(2)}
    first = romano_wolf(models, alpha=0.10, n_bootstrap=200, block_length=5, seed=11)
    second = romano_wolf(models, alpha=0.10, n_bootstrap=200, block_length=5, seed=11)
    assert first.adjusted_p == second.adjusted_p


def test_the_running_maximum_actually_binds() -> None:
    """The previous test asserts monotonicity on a fixture where it holds for free.

    A later round tests against a SMALLER surviving set, so its raw bootstrap frequency is
    smaller — but only sometimes by enough to matter. On these four models it does: without the
    running maximum, `b` (rejected in a later round than `a`) prints a p-value BELOW `a`'s, and
    the ladder inverts. The clamp shows up as the two of them landing on the same number.

    Found by probing, not by reasoning: my first fixture had raw frequencies that were already
    monotone, so deleting the clamp changed nothing and the test passed anyway.
    """
    models = {
        "a": with_edge("0.0016", 1),
        "b": with_edge("0.0014", 2),
        "c": with_edge("0.0012", 4),
        "d": noise(3),
    }
    result = romano_wolf(models, alpha=0.10, n_bootstrap=200, block_length=5, seed=11)

    assert result.rounds > 2, "the fixture must step down more than once to bind anything"
    by_statistic = sorted(result.statistics, key=lambda k: -result.statistics[k])
    ladder = [result.adjusted_p[name] for name in by_statistic]
    assert ladder == sorted(ladder), (by_statistic, result.adjusted_p)
    assert result.adjusted_p["a"] == result.adjusted_p["b"], (
        "the clamp is what makes these equal; unclamped, b sits below a",
        result.adjusted_p,
    )


def test_the_adjusted_p_does_not_depend_on_alpha() -> None:
    """A p-value is a property of the data, not of a level someone chose to test at.

    The first implementation walked the stepdown's ALPHA-REJECTION rounds, so the surviving set
    at each step — and therefore every adjusted p-value — moved with alpha. Pure noise read
    0.960 at alpha=0.05 and 0.435 at alpha=0.10. Recording that in a dossier would pin a number
    that says as much about the caller as about the strategy, and `stability.spa_p` is compared
    against a fixed 0.10 bar by someone who did not run it.

    The fix is Romano-Wolf's own construction: walk the hypotheses in STATISTIC order, so round
    j tests against "this one and everything weaker" and no threshold is consulted at all.
    """
    models = {
        "a": with_edge("0.0016", 1),
        "b": with_edge("0.0014", 2),
        "c": with_edge("0.0012", 4),
        "d": noise(3),
    }
    kwargs = {"n_bootstrap": 200, "block_length": 5, "seed": 11}
    baseline = romano_wolf(models, alpha=0.05, **kwargs).adjusted_p  # type: ignore[arg-type]

    for alpha in (0.10, 0.20, 0.30, 0.50):
        other = romano_wolf(models, alpha=alpha, **kwargs).adjusted_p  # type: ignore[arg-type]
        assert other == baseline, (alpha, other, baseline)
