"""A recorded trial names a broker and a capital tier the spec declares (§8.2, rule 4).

`TrialContext` carries `broker` and `capital_tier` into every row of the trial registry, and
rule 4 makes that registry load-bearing: every viewed trial counts, and the count is only
meaningful if the rows can be joined back to what was pre-registered.

Both are bare literals at their call sites today, and they diverge from the specs in two
different ways. S1 records `broker="NONE"`, which no spec declares — every alpha spec says
`brokers: ["FLATTRADE"]`. And both stages record `capital_tier="2L"` while every spec declares
`capital_tiers: ["2L", "5L", "10L"]`, so the evidence covers one of three declared tiers with
nothing saying so.

The first is almost certainly deliberate: S1 applies no cost model (`cost_model` is 64 zeros),
so no broker context applies and "NONE" says that. The problem is that nothing *says* it is
deliberate, and a value in a ledger column that joins to nothing looks identical to a typo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pips.search.trials import NO_BROKER

ROOT = Path(__file__).resolve().parents[2]
SPECS = sorted((ROOT / "config" / "search_spaces").glob("A*.yaml"))


def cost_context(spec_path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    context: dict[str, object] = loaded["cost_context"]
    return context


def test_there_are_specs_to_check() -> None:
    """The list is a glob, and a glob that matches nothing makes every test below vacuous."""
    assert SPECS, "no alpha specs found — every assertion in this file would pass trivially"


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.stem)
def test_the_recorded_capital_tier_is_one_the_spec_declares(spec: Path) -> None:
    """A tier outside the declared set cannot be joined back to a pre-registration.

    This does not assert that all three are run — they are not, and that gap is recorded at the
    constant rather than hidden. It asserts the weaker, checkable thing: what IS recorded was
    declared, so a typo (`2l`, `20L`) cannot enter the ledger and sit there looking like data.
    """
    from pips.search.families import CAPITAL_TIER

    declared = cost_context(spec)["capital_tiers"]
    assert isinstance(declared, list)
    assert CAPITAL_TIER in declared, f"{CAPITAL_TIER} is not among {declared}"


@pytest.mark.parametrize("spec", SPECS, ids=lambda p: p.stem)
def test_the_recorded_broker_is_declared_or_is_the_stated_absence(spec: Path) -> None:
    """ "No broker" must be a named value, not a string that happens to join to nothing.

    S1 screens before any cost model is applied, so it genuinely has no broker context. Written
    as a bare `"NONE"` that is exactly what a mistyped broker id looks like from the registry;
    named once, with a docstring, it is a claim a reader can check.
    """
    from pips.search.families import BROKER

    declared = cost_context(spec)["brokers"]
    assert isinstance(declared, list)
    assert BROKER in declared, f"{BROKER} is not among {declared}"
    assert NO_BROKER not in declared, (
        f"{NO_BROKER!r} is a declared broker in {spec.name}, so it can no longer double as the "
        "sentinel for 'no broker context' — the two meanings would be indistinguishable"
    )


def test_the_no_broker_sentinel_is_what_s1_records() -> None:
    """Named in one place and used from it, or the sentinel and its meaning drift apart."""
    source = (ROOT / "python" / "pips" / "search" / "s1.py").read_text(encoding="utf-8")

    assert 'broker="NONE"' not in source, "S1 records the sentinel as a bare literal"
    assert "NO_BROKER" in source


def test_every_spec_declares_the_same_cost_context_keys() -> None:
    """A spec missing `capital_tiers` would make its parametrized case above pass on a
    `KeyError`-free path that checked nothing about it."""
    for spec in SPECS:
        context = cost_context(spec)
        assert "brokers" in context, f"{spec.name} declares no brokers"
        assert "capital_tiers" in context, f"{spec.name} declares no capital tiers"
