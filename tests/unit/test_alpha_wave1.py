"""Alpha wave 1 — the T1 launch surface (§6 M12, §5).

M12 pre-registers A01-A08 and A12. These tests are about the *set*, not any one alpha: that
every named family is registered, that each carries falsifiers transcribed from its card, and
— the one that would be easiest to get wrong — that the gap-continuation and gap-reversal
specs are genuinely independent pre-registrations rather than one rule with a sign chosen
after the fact (§5: "continue/fade separate, never chosen ex post").
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pips.alphas.spec import AlphaSpec, DataTier, load_alpha_spec

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "config" / "search_spaces"
WAVE_1 = ("A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A12")


def specs() -> dict[str, AlphaSpec]:
    found: dict[str, AlphaSpec] = {}
    for path in sorted(SPEC_DIR.glob("A*.yaml")):
        spec = load_alpha_spec(path)
        found[spec.id] = spec
    return found


def test_every_wave_one_family_is_pre_registered() -> None:
    missing = sorted(set(WAVE_1) - set(specs()))
    assert not missing, f"M12 names {WAVE_1}; missing pre-registrations: {missing}"


@pytest.mark.parametrize("alpha_id", WAVE_1)
def test_each_spec_validates_under_rule_five(alpha_id: str) -> None:
    # Loading is validation: null models and evaluable falsifiers are required at entry.
    spec = specs()[alpha_id]
    assert spec.null_models and spec.falsifiers


@pytest.mark.parametrize("alpha_id", WAVE_1)
def test_each_alpha_is_on_the_t1_launch_surface(alpha_id: str) -> None:
    # §5: T1 (A01-A18, A27, A29, A30) is the launch surface. A wave-1 alpha claiming T2 would
    # be claiming the quote/depth archive that does not exist yet.
    assert specs()[alpha_id].data_tier is DataTier.T1


@pytest.mark.parametrize("alpha_id", WAVE_1)
def test_each_alpha_names_a_simpler_parent_to_beat(alpha_id: str) -> None:
    # Rule 5: "a more elaborate operator is admissible only if it beats its simpler parent".
    # A null set of only "zero forecast" cannot establish that.
    nulls = specs()[alpha_id].null_models
    assert len(nulls) >= 2, f"{alpha_id} names only {nulls} — no simpler parent to beat"


def test_every_spec_hash_is_distinct() -> None:
    # Two identical specs would be one trial counted twice in the multiplicity ledger, which
    # inflates M without adding a search — the opposite of the ledger's purpose.
    hashes = {aid: s.content_hash() for aid, s in specs().items()}
    assert len(set(hashes.values())) == len(hashes), f"duplicate spec hashes: {hashes}"


def test_gap_continuation_and_reversal_are_independent_pre_registrations() -> None:
    """§5: continue/fade separate, never chosen ex post — and A06's own card says so.

    The failure this prevents is subtle and common: one gap rule whose sign is decided after
    seeing which way the day went, presented afterwards as two strategies. Independent specs
    with independent hashes, distinct confirmation grids and distinct null models are what
    make that structurally impossible rather than merely discouraged.
    """
    found = specs()
    a05, a06 = found["A05"], found["A06"]
    assert a05.content_hash() != a06.content_hash()
    assert a05.parameter_domain.keys() != a06.parameter_domain.keys() or (
        a05.parameter_domain != a06.parameter_domain
    )
    assert set(a05.null_models) != set(a06.null_models)
    # A06 must carry the card's own ex-post-selection falsifier verbatim in substance.
    assert any("ex post" in f.lower() for f in a06.falsifiers)


def test_a06_treats_missing_event_metadata_as_exclusion() -> None:
    # The card makes the no-event flag mandatory. With no PIT event masters until M6, the
    # conservative reading is to EXCLUDE a name whose metadata is missing — assuming "no
    # event" would silently trade exactly the names most likely to have had one.
    a06 = specs()["A06"]
    exclusion = [n for n in a06.feature_dag if "event" in str(n).lower()]
    assert exclusion, "A06 must carry an event gate"
    assert any("exclude" in str(n).lower() for n in exclusion)


@pytest.mark.parametrize("alpha_id", WAVE_1)
def test_deferred_falsifiers_name_what_they_are_waiting_for(alpha_id: str) -> None:
    # A deferred falsifier must say which data it needs, or "deferred" becomes indefinite.
    for deferred in specs()[alpha_id].falsifiers_deferred:
        assert " — needs " in deferred, f"{alpha_id}: {deferred!r} does not name what it awaits"


def test_at_least_one_falsifier_per_alpha_is_runnable_today() -> None:
    # An alpha whose every rejection condition is deferred cannot be falsified at all, and
    # would enter the funnel with no way to fail — the exact status rule 5 exists to prevent.
    for alpha_id, spec in specs().items():
        assert spec.runnable_falsifiers, (
            f"{alpha_id} has no falsifier that can be evaluated with the data we have"
        )


def test_the_wave_is_not_five_clones_of_one_idea() -> None:
    # §7's rejection list: "five clones branded diversified". Distinct hypotheses are the
    # cheapest possible check on that, and a real one — momentum, reversal, gap and
    # seasonality must not all reduce to the same sentence.
    hypotheses = {s.hypothesis.strip().lower()[:80] for s in specs().values()}
    assert len(hypotheses) == len(specs())
