"""Backfill campaign planning (§6 M4).

The planning half is pure and tested here; only the session and the HTTP call are not.

The property worth guarding is that a campaign **states its cost before spending it**. A
backfill that starts fetching and finds out later how many calls it needed can exhaust a
day's quota on a range nobody meant to request — and the mistake is a typo away, since a
date range is two strings.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from pips.data.breeze.campaign import CampaignPlan, plan_campaign

ROOT = Path(__file__).resolve().parents[2]
CALENDAR = ROOT / "config" / "calendars" / "nse_equity.yaml"


def test_weekends_are_excluded_from_the_plan() -> None:
    # 2026-06-05 is a Friday, 06/07 the weekend, 08 the Monday.
    plan = plan_campaign(["RELIND"], date(2026, 6, 5), date(2026, 6, 8), CALENDAR)
    assert plan.days == [date(2026, 6, 5), date(2026, 6, 8)]


def test_the_call_count_is_symbols_times_days() -> None:
    plan = plan_campaign(["A", "B", "C"], date(2026, 6, 1), date(2026, 6, 5), CALENDAR)
    assert plan.days == [date(2026, 6, d) for d in (1, 2, 3, 4, 5)]
    assert plan.estimated_calls == 15


def test_an_inverted_range_is_refused() -> None:
    with pytest.raises(ValueError, match="before"):
        plan_campaign(["A"], date(2026, 6, 10), date(2026, 6, 1), CALENDAR)


def test_an_empty_symbol_list_is_refused() -> None:
    with pytest.raises(ValueError, match="symbol"):
        plan_campaign([], date(2026, 6, 1), date(2026, 6, 5), CALENDAR)


def test_a_range_with_no_trading_days_is_refused() -> None:
    # A weekend-only range is almost certainly a mistake, and silently doing nothing would
    # look like a completed campaign.
    with pytest.raises(ValueError, match="no trading days"):
        plan_campaign(["A"], date(2026, 6, 6), date(2026, 6, 7), CALENDAR)


def test_the_plan_warns_when_it_exceeds_the_daily_budget() -> None:
    # Stating the cost before spending it. A three-year U300 campaign is ~85k calls, which
    # fits one day's budget (ADR-0012) — but a wider request must say so rather than
    # discovering it at call 90,000.
    # WAS 2020-01-01, which now RAISES: since 2026-09-05 the calendar's holidays are sourced
    # and bounded, and it refuses dates it does not cover rather than guessing their trading
    # days. Planning a campaign over a span whose sessions are unknown is exactly the thing
    # worth refusing, so the fixture moved inside the covered range instead of the guard moving.
    plan = plan_campaign(
        [f"S{i}" for i in range(500)], date(2023, 1, 2), date(2026, 1, 1), CALENDAR
    )
    assert plan.estimated_calls > 100_000
    assert plan.exceeds_budget(daily_budget=90_000)
    assert not plan.exceeds_budget(daily_budget=10_000_000)


def test_the_plan_is_reportable_before_anything_is_fetched() -> None:
    plan = plan_campaign(["A", "B"], date(2026, 6, 1), date(2026, 6, 3), CALENDAR)
    summary = plan.describe()
    assert "2 symbols" in summary and "3 trading days" in summary and "6" in summary
    assert isinstance(plan, CampaignPlan)


# --------------------------------------------------------- found by mutation sweep ---
#
# `main()` was never called by any test: the whole CLI -- `--dry-run` and every exit code --
# was unexercised, and the exit code is what a scheduler reads to decide whether to resume.

from pips.data.breeze import backfill as backfill_module  # noqa: E402
from pips.data.breeze import campaign as campaign_module  # noqa: E402
from pips.data.breeze import client as client_module  # noqa: E402
from pips.data.breeze.backfill import BackfillResult  # noqa: E402

ARGS = ["--symbols", "RELIND", "--from", "2026-08-24", "--to", "2026-08-28"]


def _result(**over: object) -> BackfillResult:
    base: dict[str, object] = {
        "attempted": 5,
        "fetched": 5,
        "empty": 0,
        "errored": 0,
        "skipped": 0,
        "stopped_on_budget": False,
        "stopped_on_rate_limit": False,
    }
    base.update(over)
    return BackfillResult(**base)  # type: ignore[arg-type]


@pytest.fixture
def cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub every collaborator that costs money, and record what got called."""
    called: list[str] = []

    def no_session(*_a: object, **_k: object) -> object:
        called.append("build_session")
        return object()

    def fetcher(*_a: object, **_k: object) -> object:
        called.append("budgeted_fetcher")
        return lambda _s, _d: None

    monkeypatch.setattr(client_module, "build_session", no_session)
    monkeypatch.setattr(client_module, "budgeted_fetcher", fetcher)
    monkeypatch.setattr(
        client_module,
        "default_paths",
        lambda _root=None: (
            tmp_path / "bronze",
            tmp_path / "state" / "manifest.json",
            tmp_path / "state" / "budget.json",
        ),
    )

    def recorded_backfill(*_a: object, **_k: object) -> BackfillResult:
        called.append("run_backfill")
        return _result()

    monkeypatch.setattr(backfill_module, "run_backfill", recorded_backfill)
    return called


def test_a_dry_run_opens_no_session_and_fetches_nothing(
    cli: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole point of `--dry-run`, and nothing checked it.

    A mis-typed date range is one keystroke away and the plan exists precisely so it can be
    costed before it is spent. A `--dry-run` that reached the fetcher would spend real quota
    against a metered daily budget, on the command whose entire purpose is not to.
    """
    assert campaign_module.main([*ARGS, "--dry-run"]) == 0
    assert cli == [], f"a dry run must call none of these: {cli}"
    out = capsys.readouterr().out
    assert "backfill plan:" in out
    assert "nothing fetched" in out


def test_a_real_run_does_reach_the_fetcher(cli: list[str]) -> None:
    """The control. Without it, a `main` that fetched nothing at all would pass the test above."""
    assert campaign_module.main(ARGS) == 0
    assert "run_backfill" in cli
    assert "build_session" in cli


def test_a_rate_limited_stop_is_a_failure_exit(
    cli: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The vendor rejected us below our own configured pace, so the pace is wrong.

    Exiting 0 would tell a scheduler the campaign succeeded, and it would stop re-running —
    leaving an archive with a hole in it that no later QC can distinguish from a quiet market.
    """
    monkeypatch.setattr(
        backfill_module, "run_backfill", lambda *_a, **_k: _result(stopped_on_rate_limit=True)
    )
    assert campaign_module.main(ARGS) == 1


def test_a_budget_stop_exits_zero_but_does_not_claim_completion(
    cli: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spending the day's quota is the plan working, not the plan failing — so the exit is 0.

    A campaign costing three days of quota stops twice on its way to finishing, and a scheduler
    treating each stop as a failure would page somebody about a backfill behaving exactly as
    designed. Which means the exit code CANNOT carry the difference, and the message is the
    only thing that does: a run that stopped with work outstanding must not print "campaign
    complete." That is the same failure-that-looks-like-success this whole module is built
    against, aimed at the operator instead of the archive.
    """
    monkeypatch.setattr(
        backfill_module, "run_backfill", lambda *_a, **_k: _result(stopped_on_budget=True)
    )
    assert campaign_module.main(ARGS) == 0
    out = capsys.readouterr().out
    assert "daily budget spent" in out
    assert "campaign complete" not in out, "it did not complete; it stopped"


def test_errored_keys_are_a_failure_exit(cli: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """They were deliberately left unmarked so the next run retries them.

    That only helps if something says a next run is needed — the same argument as
    `BackfillResult.complete`, which the CLI does not use.
    """
    monkeypatch.setattr(
        backfill_module, "run_backfill", lambda *_a, **_k: _result(errored=2, fetched=3)
    )
    assert campaign_module.main(ARGS) == 1


def test_a_plan_that_cannot_be_costed_exits_two(
    cli: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Distinct from 1: nothing was attempted, so nothing is pending and retrying is pointless."""
    assert (
        campaign_module.main(["--symbols", "RELIND", "--from", "2026-08-28", "--to", "2026-08-24"])
        == 2
    )
    assert "is before start" in capsys.readouterr().out
    assert cli == [], "a plan that will not cost must not open a session"


def test_a_plan_exactly_equal_to_the_budget_does_not_exceed_it() -> None:
    """`>`, not `>=`. A plan that fits precisely fits, and warning that it does not would
    teach the reader to ignore the warning that matters."""
    plan = CampaignPlan(symbols=["A"], days=[date(2026, 8, 24), date(2026, 8, 25)])
    assert not plan.exceeds_budget(2)
    assert plan.exceeds_budget(1)


# ----------------------------------------------------- costing other intervals -------


def test_a_plan_costs_the_fetch_shape_this_code_actually_issues() -> None:
    """One call per symbol-DAY, whatever the interval — because that is what the fetcher does.

    `budgeted_fetcher` requests `ist_window(day)`, a single day, and the manifest is keyed per
    symbol-day, which is what makes resume granular. So a coarse interval buys nothing under
    this shape: a daily-bar campaign pays the same per-day toll as a 1-minute one and receives
    one candle for it. Costing it any other way is how a seed gets planned at 1,800 calls and
    spends 1.4 million.
    """
    days = [date(2026, 8, 24), date(2026, 8, 25)]
    for interval, per_day in (("1day", 1), ("30minute", 1), ("1minute", 1), ("1second", 23)):
        plan = CampaignPlan(symbols=["A", "B"], days=days, interval=interval)
        assert plan.estimated_calls == 2 * 2 * per_day, interval


def test_a_plan_also_states_what_a_range_fetch_would_cost() -> None:
    """The number that makes a seed look cheap, kept beside the one that is real.

    The vendor allows <=1,000 candles per call over an arbitrary range, so three years of daily
    bars is ONE call per symbol. This code cannot issue that call — the gap is a fetch shape,
    not a quota — and the planner says so rather than leaving the difference to be rediscovered
    in prose.
    """
    days = [date(2026, 8, 24) + timedelta(days=i) for i in range(400)]
    daily = CampaignPlan(symbols=["A"], days=days, interval="1day")
    assert daily.estimated_calls == 400, "per-day fetching pays 400 tolls for 400 candles"
    assert daily.estimated_calls_if_ranged == 1, "400 candles fit one 1,000-candle call"

    minute = CampaignPlan(symbols=["A"], days=days, interval="1minute")
    assert minute.estimated_calls == 400
    assert minute.estimated_calls_if_ranged == 150, "400 x 375 candles / 1000 per call"


def test_an_unknown_interval_is_refused_rather_than_costed_as_a_minute() -> None:
    """A typo'd interval must not silently inherit the 1-minute model and under-cost by 23x."""
    with pytest.raises(ValueError, match="unsupported interval"):
        plan_campaign(
            ["RELIND"],
            date(2026, 8, 24),
            date(2026, 8, 28),
            Path("config/calendars/nse_equity.yaml"),
            interval="1min",
        )


def test_the_described_plan_names_the_interval_it_costed() -> None:
    """A cost with no interval beside it is a number nobody can check."""
    plan = plan_campaign(
        ["RELIND"],
        date(2026, 8, 24),
        date(2026, 8, 28),
        Path("config/calendars/nse_equity.yaml"),
        interval="1second",
    )
    described = plan.describe()
    assert "1second" in described
    assert str(plan.estimated_calls) in described


def test_the_cli_takes_an_interval_and_hands_it_to_the_fetcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Costing an interval the fetcher is never told about would cost the wrong thing.

    `budgeted_fetcher`'s `interval` defaulted to 1minute and nothing passed it, so a plan
    costed at 1second would have fetched minutes — a plan and a run disagreeing about what was
    requested, with the plan the more expensive of the two and therefore the one that looks
    conservative.
    """
    seen: dict[str, object] = {}

    monkeypatch.setattr(client_module, "build_session", lambda *_a, **_k: object())
    monkeypatch.setattr(
        client_module,
        "default_paths",
        lambda _root=None: (
            tmp_path / "bronze",
            tmp_path / "state" / "manifest.json",
            tmp_path / "state" / "budget.json",
        ),
    )

    def fetcher(_client: object, _budget: object, **kw: object) -> object:
        seen.update(kw)
        return lambda _s, _d: None

    monkeypatch.setattr(client_module, "budgeted_fetcher", fetcher)
    monkeypatch.setattr(backfill_module, "run_backfill", lambda *_a, **_k: _result())

    assert campaign_module.main([*ARGS, "--interval", "1second"]) == 0
    assert seen.get("interval") == "1second", f"the fetcher was told {seen!r}"
    assert "at 1second" in capsys.readouterr().out


def test_an_unsupported_interval_stops_before_any_session(
    cli: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert campaign_module.main([*ARGS, "--interval", "1min"]) == 2
    assert "unsupported interval" in capsys.readouterr().out
    assert cli == []


# ------------------------------------------- the ranged path was unreachable ---------
#
# `run_range_backfill` had no caller outside tests. `[C-M4-10]` chunks a range so no reply can
# truncate, the row is `enforced`, and `main` called `run_backfill` — the per-symbol-day path —
# so the halved cost existed only in the plan. Worse, `describe()` said the capability did not
# exist: "{ranged} calls would serve this range if one call could span days. This fetcher
# requests one day per call." True when it was written, false since the chunker landed, and the
# operator reading it would conclude the cheap shape was unavailable.


def test_ranged_uses_the_chunked_path_and_the_default_does_not(
    cli: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both halves. Asserting only that `--ranged` reaches the ranged fetcher would pass on a
    build that reached it always, which would silently change the manifest grain of every
    existing campaign."""

    def recorded_range(*_a: object, **_k: object) -> BackfillResult:
        cli.append("run_range_backfill")
        return _result()

    monkeypatch.setattr(backfill_module, "run_range_backfill", recorded_range)
    monkeypatch.setattr(client_module, "ranged_fetcher", lambda *_a, **_k: lambda *_x: None)

    assert campaign_module.main([*ARGS, "--ranged"]) == 0
    assert "run_range_backfill" in cli and "run_backfill" not in cli

    cli.clear()
    assert campaign_module.main(ARGS) == 0
    assert "run_backfill" in cli and "run_range_backfill" not in cli


def test_the_plan_names_the_cost_the_ranged_path_can_actually_deliver() -> None:
    """`estimated_calls_if_ranged` is the VENDOR's allowance — it needs windows ending
    mid-session, and the bronze layout is keyed per day. Advertising it as the alternative
    points the operator at a number no code path can reach, while the achievable one
    (`estimated_calls_if_chunked`) went unmentioned.
    """
    plan = plan_campaign(["A", "B"], date(2026, 6, 1), date(2026, 8, 31), CALENDAR)
    summary = plan.describe()

    assert plan.estimated_calls_if_chunked is not None
    assert str(plan.estimated_calls_if_chunked) in summary
    assert "--ranged" in summary, "it names the flag that delivers the cheaper number"
    assert "one day per call" not in summary, "the fetcher can span days now"


def test_switching_grain_mid_campaign_is_flagged(
    cli: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A manifest holding per-symbol-day keys means those days are done at DAY grain.

    A ranged run keys on `SYMBOL:INTERVAL:START:END`, so none of them match and every day is
    re-fetched — at full price, silently, while the manifest says the work was already done.
    Not refused, because switching shapes is a legitimate thing to want; said out loud, because
    doing it by accident costs a second campaign.
    """
    manifest = tmp_path / "state" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"outcomes": {"RELIND:2026-08-24": "OK", "RELIND:2026-08-25": "OK"}}')

    monkeypatch.setattr(backfill_module, "run_range_backfill", lambda *_a, **_k: _result())
    monkeypatch.setattr(client_module, "ranged_fetcher", lambda *_a, **_k: lambda *_x: None)

    assert campaign_module.main([*ARGS, "--ranged"]) == 0

    out = capsys.readouterr().out
    assert "2 symbol-day" in out
    assert "re-fetched" in out


def test_the_ranged_run_is_handed_the_whole_span(
    cli: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHICH function was called is not the property; what it was called with is.

    `run_range_backfill` takes a start and an end. Passing the first day as both would fetch
    one session of a three-year range, mark it done, and report success — a total data loss
    that every count in the report agrees with.
    """
    seen: dict[str, object] = {}

    def recorded(
        symbols: object, start: object, end: object, *_a: object, **_k: object
    ) -> BackfillResult:
        seen.update(symbols=symbols, start=start, end=end)
        return _result()

    monkeypatch.setattr(backfill_module, "run_range_backfill", recorded)
    monkeypatch.setattr(client_module, "ranged_fetcher", lambda *_a, **_k: lambda *_x: None)

    assert campaign_module.main([*ARGS, "--ranged"]) == 0

    assert seen["start"] == date(2026, 8, 24)
    assert seen["end"] == date(2026, 8, 28), "the span ends at the plan's LAST day"


def test_a_manifest_of_range_keys_does_not_warn_about_itself(
    cli: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The warning is about a GRAIN SWITCH, so a resumed ranged run must not trip it.

    Range keys carry three colons (`SYMBOL:INTERVAL:START:END`) and day keys one. Counting
    "at least one" would make every resume warn that it is about to re-fetch work it is in fact
    about to skip — and a warning that fires every time is one nobody reads.
    """
    manifest = tmp_path / "state" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"outcomes": {"RELIND:1minute:2026-08-24:2026-08-28": "OK"}}')

    monkeypatch.setattr(backfill_module, "run_range_backfill", lambda *_a, **_k: _result())
    monkeypatch.setattr(client_module, "ranged_fetcher", lambda *_a, **_k: lambda *_x: None)

    assert campaign_module.main([*ARGS, "--ranged"]) == 0
    assert "re-fetched" not in capsys.readouterr().out


def test_another_symbols_day_keys_do_not_warn(
    cli: list[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The archive holds every symbol ever fetched. Warning on keys belonging to symbols this
    run does not touch would fire on a 5,000-name manifest for a one-symbol campaign."""
    manifest = tmp_path / "state" / "manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"outcomes": {"INFY:2026-08-24": "OK", "TCS:2026-08-25": "OK"}}')

    monkeypatch.setattr(backfill_module, "run_range_backfill", lambda *_a, **_k: _result())
    monkeypatch.setattr(client_module, "ranged_fetcher", lambda *_a, **_k: lambda *_x: None)

    assert campaign_module.main([*ARGS, "--ranged"]) == 0
    assert "re-fetched" not in capsys.readouterr().out


# 200 symbols over three years at 1-minute: 156,800 calls per symbol-day and 78,400 chunked,
# against a 90,000 effective daily budget. The only span where the two costings DISAGREE about
# whether the plan fits -- `ARGS` is 1 symbol over 5 days, five calls, which fits either way and
# is why my first version of these tests passed without testing anything.
BIG = [
    "--symbols",
    ",".join(f"SYM{i:03d}" for i in range(200)),
    "--from",
    "2023-09-04",
    "--to",
    "2026-09-03",
    "--interval",
    "1minute",
]


def test_the_budget_warning_costs_the_shape_that_will_actually_run(
    cli: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Observed live on the 2026-09-04 daily seed.

    A `--ranged` run of 3,101 symbols warned "this plan exceeds today's remaining budget" while
    spending 3,101 of 90,000 calls. `exceeds_budget` costed `estimated_calls` -- the
    per-symbol-day toll, 2,431,184 there -- for a run that was never going to pay it.

    A warning that fires on a run using 3% of the budget is one an operator learns to skip, and
    the next time it fires it will be right.
    """
    monkeypatch.setattr(backfill_module, "run_range_backfill", lambda *_a, **_k: _result())
    monkeypatch.setattr(client_module, "ranged_fetcher", lambda *_a, **_k: lambda *_x: None)

    assert campaign_module.main([*BIG, "--ranged"]) == 0

    assert "exceeds today's remaining budget" not in capsys.readouterr().out


def test_an_unranged_run_that_really_does_exceed_still_warns(
    cli: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """The other direction, on the SAME plan: silencing the ranged case must not silence the
    warning everywhere. Unranged, those 200 symbols cost 156,800 calls.

    WHAT CHANGED 2026-09-05: there is no daily cap to stop on any more — the owner asked for
    "no fixed limits, basis real time responding conditions of api", and the run now stops when
    the VENDOR rejects. The warning was NOT removed with the cap, because the thing it tells an
    operator is still true and still useful: this plan is far larger than any recorded per-day
    figure and will span days. Only its basis changed, from a cap that refuses to a reference
    that informs."""
    assert campaign_module.main(BIG) == 0

    assert "exceeds today's remaining budget" in capsys.readouterr().out
