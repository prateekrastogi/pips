"""M7's universe refresh cadence  (§4.1, `[C-UNIV-03]`).

The blueprint's guardrail is one line: **"Membership fixed for each session."** A universe that
changes mid-session is not a universe; it is a decision made after seeing part of the day.

So membership for a session comes from a refresh **at or before** it, and a session earlier than
the first refresh has **none**. That case is refused rather than filled in with the first
refresh's list: applying a membership decided later to an earlier session is lookahead wearing
the costume of a default, and it leaves no trace — the panel simply contains names that were not
eligible yet.

**Refreshes are computed over the SESSION list, never over calendar dates.** A weekly refresh is
the first *session* of each week, so a Monday holiday moves it to Tuesday by construction. A
date-based rule would schedule a refresh on a day the exchange was shut, and the project's own
calendar still carries `holidays_verified: false` — so the session list is the caller's to
supply and to have verified (`require_verified_holidays()`).
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

__all__ = ["SUPPORTED_CADENCES", "governing_refresh", "refresh_sessions"]

SUPPORTED_CADENCES: frozenset[str] = frozenset({"weekly", "monthly", "daily"})
"""The blueprint's registered cadences: *weekly, monthly; daily as stress*. Daily carries no
stability at all and is kept so the others can be compared against it."""


def _bucket(session: date, cadence: str) -> object:
    if cadence == "weekly":
        # ISO year AND week: week 1 of two adjacent years is not one bucket.
        return session.isocalendar()[:2]
    if cadence == "monthly":
        return (session.year, session.month)
    return session


def refresh_sessions(sessions: Sequence[date], *, cadence: str) -> tuple[date, ...]:
    """The sessions on which membership is recomputed.

    The FIRST session of each bucket, taken from the sessions that actually happened.
    """
    if cadence not in SUPPORTED_CADENCES:
        raise ValueError(
            f"cadence {cadence!r} is not one of the registered {sorted(SUPPORTED_CADENCES)}. "
            "An unregistered cadence is a policy nobody declared."
        )
    ordered = list(sessions)
    if any(b <= a for a, b in itertools.pairwise(ordered)):
        raise ValueError(
            "sessions are not in strictly ascending order. 'The first session of the week' "
            "would then name whichever row happened to come first, and the caller's session "
            "source is wrong in a way this cannot repair."
        )

    picks: list[date] = []
    seen: set[object] = set()
    for session in ordered:
        bucket = _bucket(session, cadence)
        if bucket not in seen:
            seen.add(bucket)
            picks.append(session)
    return tuple(picks)


def governing_refresh(session: date, refreshes: Sequence[date]) -> date:
    """Which refresh's membership applies to ``session``.

    At-or-before, because a refresh is computed from prior sessions and applied at the open: the
    day it lands on is governed by it, not by the one before.

    Raises for a session earlier than every refresh. There is no membership to apply, and
    reaching forward for one would date a decision to before it was made.
    """
    eligible = [r for r in refreshes if r <= session]
    if not eligible:
        raise LookupError(
            f"session {session} falls before the first refresh"
            + (f" ({min(refreshes)})" if refreshes else " and no refreshes were supplied")
            + ". There is no membership for it, and borrowing a later refresh's would apply a "
            "decision to sessions that preceded it."
        )
    return max(eligible)
