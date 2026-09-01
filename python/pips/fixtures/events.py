"""An event-status source for generated fixtures  (§6 M12, A06).

A06 excludes any name whose event status is not ``CLEAR``, and the default is ``UNKNOWN``, so
with no source wired it forecasts nothing — deliberately. Its spec is explicit: *missing event
metadata => EXCLUDE the name, never assume no event.* That is why A06 has never entered a
search, and why it must not be let in by weakening the rule.

For GENERATED fixtures, ``CLEAR`` is not an assumption. The enum defines it as "we have coverage
for this name and date, and there is no event", and both halves are true by construction: the
generator produced every price in the panel, so coverage is complete and no corporate action
exists to have coverage OF.

**The danger is a source that answers CLEAR to anything.** Pointed at a real symbol it converts
A06's careful refusal into a blanket permission — the exact failure the tri-state exists to
prevent, arriving through the object built to work around it. So this is an ALLOWLIST of names
known to be synthetic, and everything else is ``UNKNOWN``.

It takes no arguments on purpose. A source that derived its allowlist from the panel it was
handed would mark every name in a real panel CLEAR: the same blanket permission by a different
route.
"""

from __future__ import annotations

from pips.alphas.t1._common import EventStatus, EventStatusSource
from pips.fixtures.generate import WIDE_SPEC, FixtureSpec

__all__ = ["GENERATED_SYMBOLS", "fixture_event_source"]

GENERATED_SYMBOLS: frozenset[str] = frozenset(FixtureSpec().symbols) | frozenset(WIDE_SPEC.symbols)
"""Every symbol the fixture generator produces. Checked against the specs by a meta-test, so a
new spec cannot go unrepresented — a generated name missing from here would be excluded by A06
and look like a name with no event coverage, which is a quieter failure than a crash."""


def fixture_event_source() -> EventStatusSource:
    """``symbol -> CLEAR`` for generated names, ``UNKNOWN`` for everything else."""

    def source(symbol: str) -> EventStatus:
        return EventStatus.CLEAR if symbol in GENERATED_SYMBOLS else EventStatus.UNKNOWN

    return source
