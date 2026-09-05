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
    # Fake clock: with the REAL one this loop slept ~400s and silently doubled every ladder.
    now = {"t": 0.0}
    p = pacer_for(
        str(tmp_path), sleep=lambda s: now.__setitem__("t", now["t"] + s), clock=lambda: now["t"]
    )
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


def test_a_rate_limit_stop_tells_the_operator_to_re_run_not_to_edit_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """MEASURED 2026-09-05: the first paced re-fetch ran 800 calls at ~600/min, took one
    RATE_LIMITED, stopped cleanly, and the pacer doubled its interval to 0.2s and persisted it.
    The CLI then printed: "rejected us BELOW the configured pace, so the pace is wrong -- lower
    max_calls_per_minute in config/breeze.yaml rather than retrying."

    Every clause of that is now false. There is no configured pace -- the pacer replaced it.
    `max_calls_per_minute` is no longer read by the campaign. And "rather than retrying" would
    stop an operator from doing the one correct thing: the interval has ALREADY been learned and
    written down, so re-running resumes slower and finishes. A rate-limit stop is the mechanism
    working, not a misconfiguration, and the message must say so -- and exit like the budget
    stop does, because it is the same kind of event: clean, progress saved, resume.
    """

    from pips.data.breeze import backfill as backfill_module
    from pips.data.breeze import campaign

    # A run that stops on the vendor's rejection, with the pacer having learned 0.2s.
    class Stopped:
        attempted, fetched, empty, errored, skipped = 800, 690, 109, 0, 0
        stopped_on_rate_limit, stopped_on_budget = True, False

    monkeypatch.setenv("PIPS_DATA_ROOT", str(tmp_path))
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "pacing.json").write_text('{"interval": 0.2}', encoding="utf-8")
    monkeypatch.setattr(backfill_module, "run_range_backfill", lambda *a, **k: Stopped())
    # `main()` imports the client module LOCALLY, so it must be patched where it lives.
    from pips.data.breeze import client as client_module

    monkeypatch.setattr(client_module, "build_session", lambda: object())

    code = campaign.main(
        [
            "--symbols",
            "RELIND",
            "--from",
            "2026-08-24",
            "--to",
            "2026-08-28",
            "--ranged",
            "--interval",
            "1day",
            "--data-root",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out

    assert "max_calls_per_minute" not in out, "that knob is no longer read; naming it misdirects"
    assert "BELOW the configured pace" not in out
    assert "re-run" in out.lower() or "run again" in out.lower(), out
    assert "0.2" in out, "the operator should see the pace the next run will start from"
    assert code == 0, "a clean, resumable stop -- the same class of event as the budget stop"
