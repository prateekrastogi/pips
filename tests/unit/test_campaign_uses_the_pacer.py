"""The campaign paces on vendor replies, not on a preset cap.

Owner, 2026-09-05: *"run it to maximum and without any limits, basis real time responding
conditions of api."*

`AdaptivePacer` was written and swept a day before anything called it, and the fetchers were
retyped to accept it — and the CLI still constructed a `CallBudget`, so a real campaign would
have paced on the same unverified 75/min constant while the log claimed otherwise. That is this
project's signature defect (a capability built and left unreachable) appearing in the very
change meant to fix pacing, and it is what this test exists to prevent recurring.

`pacer_for` is the seam: one named function, so "does the campaign use it" is a question with an
answer rather than a guess about import graphs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pips.data.breeze.campaign import pacer_for
from pips.data.breeze.pacing import AdaptivePacer


def test_the_campaign_builds_an_adaptive_pacer(tmp_path: Path) -> None:
    p = pacer_for(str(tmp_path))
    assert isinstance(p, AdaptivePacer)


def test_it_has_no_fixed_ceiling_to_refuse_against(tmp_path: Path) -> None:
    """The instruction was 'without any limits'. Pacing is the mechanism, not a call count."""
    p = pacer_for(str(tmp_path))
    assert not hasattr(p, "daily_cap"), "a preset cap is the guessed number this replaces"
    for _ in range(500):
        p.acquire()  # must never raise: no budget to exceed
    assert p.calls == 500


def test_it_remembers_across_runs_under_the_data_root(tmp_path: Path) -> None:
    """Persistence is the whole value: run_backfill STOPS on the first rejection, so a learned
    rate that does not survive the process is relearned by being rejected again — a day each."""
    from pips.data.breeze.ingest import ResponseKind

    first = pacer_for(str(tmp_path))
    first.observe(ResponseKind.RATE_LIMITED)
    learned = first.interval

    second = pacer_for(str(tmp_path))
    assert second.interval == pytest.approx(learned)


def test_the_state_lives_on_the_data_root_not_the_repo(tmp_path: Path) -> None:
    """Rule 14: runtime state lives on the VM volume, never in the checkout."""
    p = pacer_for(str(tmp_path))
    assert p.state_path is not None
    assert str(p.state_path).startswith(str(tmp_path))
