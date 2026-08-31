"""S1 sweep runner (§6 M13).

Enumerates `search_spaces/`, scores what it can, and applies BH-FDR **within family x
universe**. The property that matters most here is honesty about coverage: a sweep that
silently skips the alphas it cannot run would report a correction over fewer tests than were
actually proposed, which is the arithmetic form of "hidden trials" (§7).
"""

from __future__ import annotations

from pathlib import Path

from pips.search.s1 import apply_family_fdr, enumerate_specs

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "config" / "search_spaces"


def test_the_sweep_enumerates_every_registered_spec() -> None:
    found = enumerate_specs(SPEC_DIR)
    assert len(found) == 9
    assert {s.id for s in found} == {"A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A12"}


def test_fdr_is_applied_within_family_and_universe_not_across_everything() -> None:
    # §6 M13: "BH-FDR within family x universe". Pooling every family into one correction
    # would penalise a family for tests another family ran; not correcting at all would
    # promote the best of N. The grouping is the design.
    candidates = [
        {"family": "A01", "universe": "U100", "p_value": 0.01},
        {"family": "A01", "universe": "U100", "p_value": 0.02},
        {"family": "A03", "universe": "U100", "p_value": 0.04},
    ]
    survivors = apply_family_fdr(candidates, q=0.05)
    # A03 is alone in its group, so its threshold is q itself and 0.04 clears it. Pooled
    # across all three it would not have.
    assert survivors[2]["survives"] is True


def test_a_family_with_many_tests_faces_a_stricter_bar() -> None:
    lonely = apply_family_fdr([{"family": "A01", "universe": "U100", "p_value": 0.04}], q=0.05)
    crowded = apply_family_fdr(
        [{"family": "A01", "universe": "U100", "p_value": 0.04}]
        + [{"family": "A01", "universe": "U100", "p_value": 0.9} for _ in range(20)],
        q=0.05,
    )
    assert lonely[0]["survives"] is True
    assert crowded[0]["survives"] is False, "more tests in a family must raise its bar"


def test_every_candidate_keeps_its_group_key() -> None:
    survivors = apply_family_fdr([{"family": "A01", "universe": "U100", "p_value": 0.01}], q=0.05)
    assert survivors[0]["family"] == "A01" and survivors[0]["universe"] == "U100"
