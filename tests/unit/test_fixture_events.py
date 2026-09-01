"""An event source for generated fixtures  (§6 M12, A06).

A06 excludes any name whose event status is not CLEAR, and the default is UNKNOWN, so with no
source wired it forecasts nothing — deliberately. Its spec is explicit: *missing event metadata
=> EXCLUDE the name, never assume no event.* That is why A06 has never entered a search.

For GENERATED fixtures, CLEAR is not an assumption. `EventStatus.CLEAR` means "we have coverage
for this name and date, and there is no event", and both halves are true by construction: the
generator produced every price, so coverage is complete and there are no corporate actions.

**The danger is a source that answers CLEAR to anything.** Pointed at a real symbol it would
turn A06's careful refusal into a blanket permission, which is precisely the failure the
tri-state exists to prevent. So the source answers CLEAR only for names it knows were generated,
and UNKNOWN for everything else — an allowlist, not a default.
"""

from __future__ import annotations

import pytest

from pips.alphas.t1._common import EventStatus
from pips.fixtures.events import GENERATED_SYMBOLS, fixture_event_source
from pips.fixtures.generate import WIDE_SPEC, FixtureSpec


def test_generated_names_are_clear() -> None:
    source = fixture_event_source()
    for symbol in FixtureSpec().symbols:
        assert source(symbol) is EventStatus.CLEAR


def test_the_wide_panel_names_are_clear_too() -> None:
    source = fixture_event_source()
    for symbol in WIDE_SPEC.symbols:
        assert source(symbol) is EventStatus.CLEAR


@pytest.mark.parametrize("symbol", ["RELIANCE", "TCS", "SBIN", "INFY", ""])
def test_a_name_it_did_not_generate_is_unknown(symbol: str) -> None:
    """The safety property, and the whole reason this is an allowlist.

    A source that answers CLEAR to anything turns A06's refusal into blanket permission the
    moment it meets a real symbol — the exact failure the tri-state exists to prevent, arriving
    through the object built to work around it.
    """
    assert fixture_event_source()(symbol) is EventStatus.UNKNOWN


def test_the_allowlist_is_exactly_the_shipped_specs() -> None:
    """A meta-test, so a new fixture spec cannot silently go unrepresented.

    A generated name missing from the list would be excluded by A06 and look like a name with no
    event coverage, which is a different and much quieter failure than a crash.
    """
    assert frozenset(FixtureSpec().symbols) | frozenset(WIDE_SPEC.symbols) == GENERATED_SYMBOLS


def test_the_source_is_not_a_dict_get_over_the_panel() -> None:
    """It must not derive its allowlist from whatever panel it is handed.

    Reading the symbols out of the data would make every name in a real panel CLEAR — the same
    blanket permission, arrived at by a different route.
    """
    import inspect

    signature = inspect.signature(fixture_event_source)
    assert not signature.parameters, "the allowlist is declared, never inferred from data"
