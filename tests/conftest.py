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
