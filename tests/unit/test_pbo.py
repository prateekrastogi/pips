"""CSCV and the Probability of Backtest Overfitting  (§6 M18).

CSCV asks a question no in-sample number can answer: **when I pick the best config on half the
data, how often is it below median on the other half?** If that happens about half the time,
the selection procedure is choosing noise, and it says so without needing to know which config
is "really" good.

Three things this implementation insists on:

**All combinations, not a sample.** The "combinatorially symmetric" in the name is the method:
every way of splitting S blocks into two halves of S/2, so that each split and its complement
both appear. Sampling combinations to go faster produces a different estimator with a different
variance, and calling the result PBO would be reporting a number nobody computed.

**Boundary purge.** §6 M18 asks for it, and the reason is the same as M15's: a label spanning
the boundary between an in-sample block and an out-of-sample one puts the same bars on both
sides. The IS-best config then looks good OOS for a reason that has nothing to do with skill —
which biases PBO **down**, i.e. toward declaring the procedure sound.

**The trials it consumes are the trials rule 4 counts.** PBO evaluates N configs; those are N
viewed trials, and a PBO computed over configs the multiplicity ledger never saw is a
correction that flatters twice.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from pips.validation.pbo import probability_of_backtest_overfitting


def noise_configs(n_configs: int = 8, n_obs: int = 120) -> dict[str, list[Decimal]]:
    """Configs with no edge: which one wins in-sample is an accident of the split.

    Deterministic but irregular — coprime multipliers, because a tidy pattern makes every
    config's series a shifted copy of every other and the ranking degenerates.
    """
    return {
        f"c{c:02d}": [Decimal(((t * 7 + c * 13) % 23) - 11) / Decimal(1000) for t in range(n_obs)]
        for c in range(n_configs)
    }


def one_real_edge(n_configs: int = 8, n_obs: int = 120) -> dict[str, list[Decimal]]:
    """The same noise, plus one config with a genuine, persistent edge."""
    out = noise_configs(n_configs, n_obs)
    out["WINNER"] = [
        Decimal("0.004") + Decimal(((t * 11) % 17) - 8) / Decimal(4000) for t in range(n_obs)
    ]
    return out


# ------------------------------------------------------------ the claim ----------------


def test_pure_noise_gives_a_high_probability_of_overfitting() -> None:
    """With no real edge, the in-sample winner is a coin flip out of sample.

    PBO near 0.5 is the correct answer, and it is the whole point of the statistic: it
    detects a selection procedure choosing noise WITHOUT being told which config is good.
    """
    result = probability_of_backtest_overfitting(noise_configs(), n_blocks=6)
    assert result.pbo > 0.3, result.describe()


def test_a_persistent_edge_gives_a_low_probability_of_overfitting() -> None:
    # The control. Without it, a high PBO could be what this function always returns.
    result = probability_of_backtest_overfitting(one_real_edge(), n_blocks=6)
    assert result.pbo < 0.2, result.describe()
    assert result.most_selected == "WINNER"


def test_the_two_cases_are_clearly_separated() -> None:
    noise = probability_of_backtest_overfitting(noise_configs(), n_blocks=6)
    edge = probability_of_backtest_overfitting(one_real_edge(), n_blocks=6)
    assert noise.pbo > edge.pbo + 0.2, f"noise {noise.pbo} vs edge {edge.pbo}"


# ------------------------------------------------------------ combinatorics ------------


def test_every_combination_is_evaluated_not_a_sample() -> None:
    """C(6,3) = 20 splits, and all twenty are used.

    Sampling would give a different estimator with a different variance, and reporting it as
    PBO would be reporting a number nobody computed.
    """
    result = probability_of_backtest_overfitting(noise_configs(), n_blocks=6)
    assert result.n_splits == 20


def test_an_odd_number_of_blocks_is_refused() -> None:
    # S/2 blocks per side requires an even S. Rounding would make the two sides unequal and
    # the symmetry the method is named for would be gone.
    with pytest.raises(ValueError, match="even"):
        probability_of_backtest_overfitting(noise_configs(), n_blocks=5)


def test_fewer_than_two_configs_cannot_be_ranked() -> None:
    single = {"only": [Decimal("0.01")] * 120}
    with pytest.raises(ValueError, match="at least 2"):
        probability_of_backtest_overfitting(single, n_blocks=6)


def test_configs_of_unequal_length_are_refused() -> None:
    ragged = noise_configs()
    ragged["c00"] = ragged["c00"][:-5]
    with pytest.raises(ValueError, match="same length"):
        probability_of_backtest_overfitting(ragged, n_blocks=6)


# ------------------------------------------------------------ the purge ----------------


def test_no_in_sample_label_reaches_into_an_out_of_sample_block() -> None:
    """§6 M18's boundary purge, asserted as the STRUCTURAL guarantee it actually is.

    A label spanning an IS/OOS boundary puts the same bars on both sides, so the halves are
    not independent and the "out-of-sample" half is partly in-sample. After purging, no
    in-sample observation's label window reaches across.

    An earlier version of this test asserted a DIRECTION instead — that leakage biases PBO
    downward. That story is plausible and I could not reproduce it: on noise, and again on a
    fixture with genuinely overlapping labels, purging LOWERED the statistic rather than
    raising it. Removing data also adds estimation noise. Rather than keep an assertion the
    experiments contradict, this checks what the purge actually guarantees.
    """
    from pips.validation.pbo import split_indices

    blocks = [list(range(i * 20, (i + 1) * 20)) for i in range(6)]
    horizon = 5
    for is_set in ({0, 1, 2}, {0, 2, 4}, {3, 4, 5}, {1, 3, 5}):
        is_index, oos_index = split_indices(blocks, is_set, horizon)
        oos = set(oos_index)
        for i in is_index:
            assert not any(j in oos for j in range(i + 1, i + horizon + 1)), (
                f"IS observation {i} labels through {i + horizon}, which reaches OOS"
            )


def test_without_the_purge_labels_do_reach_across() -> None:
    """The control: with horizon 0 nothing is removed, and the leak is present.

    Without this, the assertion above would hold for a purge that removed everything, or for
    a split that never put adjacent blocks on opposite sides.
    """
    from pips.validation.pbo import split_indices

    blocks = [list(range(i * 20, (i + 1) * 20)) for i in range(6)]
    is_index, oos_index = split_indices(blocks, {0, 1, 2}, horizon=0)
    oos = set(oos_index)
    assert any(any(j in oos for j in range(i + 1, i + 6)) for i in is_index), (
        "unpurged, an IS label must reach into OOS — or the fixture proves nothing"
    )


def test_the_purge_removes_observations_and_reports_how_many() -> None:
    unpurged = probability_of_backtest_overfitting(noise_configs(), n_blocks=6, horizon=0)
    purged = probability_of_backtest_overfitting(noise_configs(), n_blocks=6, horizon=5)
    assert unpurged.observations_purged == 0
    assert purged.observations_purged > 0


def test_a_purge_that_would_empty_a_block_is_refused() -> None:
    # Purging more than a block holds leaves nothing to evaluate, and a PBO over empty blocks
    # is a number with no data behind it.
    with pytest.raises(ValueError, match="purge"):
        probability_of_backtest_overfitting(noise_configs(n_obs=60), n_blocks=6, horizon=50)


# ------------------------------------------------------------ shape --------------------


def test_the_result_is_reproducible() -> None:
    configs = one_real_edge()
    assert probability_of_backtest_overfitting(
        configs, n_blocks=6
    ) == probability_of_backtest_overfitting(configs, n_blocks=6)


def test_the_report_names_what_was_selected() -> None:
    text = probability_of_backtest_overfitting(one_real_edge(), n_blocks=6).describe()
    assert "PBO" in text and "WINNER" in text


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "pbo-cscv" in CHECK_REGISTRY
    resolve_check("pbo-cscv")


def test_only_crossing_boundaries_are_purged() -> None:
    """The purge is MINIMAL, not merely sufficient.

    With blocks {0,1,2} in-sample and {3,4,5} out, only the 2→3 boundary crosses. Purging the
    others removes data for no reason — the structural guarantee still holds, so nothing else
    in this file notices, and a mutation purging every boundary survived until now.

    "Arbitrary caution is a parameter" is the same argument the walk-forward split makes for
    purging exactly `horizon` samples and no more.
    """
    from pips.validation.pbo import split_indices

    blocks = [list(range(i * 20, (i + 1) * 20)) for i in range(6)]
    is_index, oos_index = split_indices(blocks, {0, 1, 2}, horizon=5)

    assert len(is_index) + len(oos_index) == 120 - 5, (
        "exactly one boundary crosses, so exactly one block's tail may be removed"
    )
    assert 19 in is_index, "block 0 is entirely in-sample; its tail must survive"
    assert 39 in is_index, "block 1's neighbour is also in-sample; its tail must survive"
    # Block 2 spans 40-59, so its last five are 55-59: index 59 goes, 54 stays. (My first
    # version asserted 54 was removed — an off-by-one in the test, not the purge.)
    assert 59 not in is_index, "block 2 crosses into OOS, so its last 5 go"
    assert 54 in is_index, "and only its last 5 — 54 is the sixth from the end"
    assert 79 in oos_index and 99 in oos_index, "OOS-to-OOS boundaries are not crossings"


def test_the_winner_is_compared_against_the_median_not_the_mean() -> None:
    """PBO is defined on the RELATIVE RANK, so the comparison is to the median.

    One catastrophically bad config drags the OOS MEAN far below the median while never being
    selected in-sample. Winners then sit above the mean and below the median, and the two
    statistics disagree: 0.65 against the median, 0.80 against the mean.

    My first attempt used an outlier that was hugely GOOD — which simply won every split, so
    it was never below either statistic and both agreed. The distinction needs the outlier to
    be one the selection does not pick.
    """
    n_obs = 120
    configs: dict[str, list[Decimal]] = {
        f"c{c:02d}": [Decimal(((t * 7 + c * 13) % 23) - 11) / Decimal(1000) for t in range(n_obs)]
        for c in range(6)
    }
    configs["DISASTER"] = [Decimal("-0.05")] * n_obs

    result = probability_of_backtest_overfitting(configs, n_blocks=6)
    assert result.pbo == 0.65, (
        f"against the median this is 0.65; against the mean it is 0.80, and the mutation "
        f"swapping them must not pass. Got {result.pbo}"
    )
