"""Shared test helpers.

`uncommented` exists because the same mistake has now been made three times in this repository:
a guard that matches text in a file fires on a COMMENT that documents the very thing the guard
forbids.

1. The Corwin-Schultz check (`test_execution_costs.py`) matched its own module docstring
   explaining why the estimator is absent. Rewritten to scan the AST.
2. The deploy service-list check (`test_deploy_guard.py`) matched the comment recording the
   drift bug it was written to prevent.
3. The order-plane check below matched a comment in `.env` stating that `PIPS_LIVE=1` must
   never be set there.

Each time the local fix was easy and each time I re-derived it. A guard that punishes writing
down *why* something is forbidden teaches people to delete the explanation, which costs more
than the guard is worth — so the rule lives here once, and text-matching guards use it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

__all__ = ["uncommented"]


def uncommented(text: str, marker: str = "#") -> str:
    """The lines of ``text`` that are not comments.

    Whole-line comments only. An inline trailing comment is left alone deliberately: stripping
    after a marker would corrupt any line that legitimately contains one, and the failure mode
    this guards against is prose ABOUT the forbidden thing, which is written on its own lines.
    """
    return "\n".join(line for line in text.splitlines() if not line.strip().startswith(marker))


@pytest.fixture
def strip_comments() -> Callable[[str], str]:
    """:func:`uncommented` as a fixture, so tests need no import path gymnastics."""
    return uncommented


@pytest.fixture
def unverified_calendar() -> Any:
    """The repo calendar with its holiday list unsourced, for the unverified-path guards.

    Until 2026-09-05 the shipped calendar had no holidays, so every guard that behaves
    differently on an unverified list was tested against the repo's own file. Then the list was
    sourced from NSE and those tests broke -- correctly. One of them says in as many words
    "pinned so a future holiday source cannot silently invert it", and a future holiday source
    is precisely what arrived.

    The guards are about UNVERIFIED CALENDARS, not about this repo's calendar, so they are handed
    one instead of being deleted, and the verified path gets its own assertions beside them.
    """
    from pathlib import Path

    from pips.core.calendar import load_calendar

    root = Path(__file__).resolve().parent.parent
    calendar = load_calendar(root / "config" / "calendars" / "nse_equity.yaml")
    return calendar.model_copy(
        update={
            "holidays": [],
            "holidays_source": None,
            "holidays_verified_on": None,
            "holidays_covering_start": None,
            "holidays_covering_end": None,
        }
    )
