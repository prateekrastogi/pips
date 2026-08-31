"""Backfill campaign planning  (§6 M4).

A campaign states its cost **before** spending it. A backfill that starts fetching and works
out later how many calls it needed can burn a day's quota on a range nobody meant to request,
and that mistake is one typo away -- a date range is two strings.

Pure: no session, no network. The planning is what can be got wrong quietly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from pips.core.calendar import load_calendar

__all__ = ["CampaignPlan", "main", "plan_campaign"]


@dataclass(frozen=True)
class CampaignPlan:
    """What a campaign will attempt, costed."""

    symbols: list[str]
    days: list[date]

    @property
    def estimated_calls(self) -> int:
        """One call per symbol per day at 1-minute granularity.

        A full NSE session is 375 candles, comfortably inside the 1,000-per-call cap, so one
        call covers one symbol-day. Finer intervals would need chunking (SAL-0002's
        DAYS_PER_CALL), which this planner does not yet do -- and says so rather than
        under-costing a request it cannot serve.
        """
        return len(self.symbols) * len(self.days)

    def exceeds_budget(self, daily_budget: int) -> bool:
        return self.estimated_calls > daily_budget

    def describe(self) -> str:
        return (
            f"{len(self.symbols)} symbols x {len(self.days)} trading days "
            f"= {self.estimated_calls} calls "
            f"({self.days[0]} to {self.days[-1]})"
        )


def plan_campaign(symbols: list[str], start: date, end: date, calendar_path: Path) -> CampaignPlan:
    """Enumerate the symbol-days a campaign would fetch.

    Weekends are dropped from the calendar. Exchange holidays are NOT -- the holiday list is
    still unverified (M6 sources it), so a holiday is left in the plan and resolves itself at
    fetch time: Breeze returns an empty reply, the manifest marks it EMPTY, and it is never
    fetched again. Guessing holidays here would risk skipping a real trading day, which is the
    more expensive error.
    """
    if not symbols:
        raise ValueError("a campaign needs at least one symbol")
    if end < start:
        raise ValueError(f"end {end} is before start {start}")

    calendar = load_calendar(calendar_path)
    days: list[date] = []
    day = start
    while day <= end:
        if calendar.is_trading_day(day):
            days.append(day)
        day += timedelta(days=1)

    if not days:
        raise ValueError(
            f"no trading days between {start} and {end} — a campaign over none of them would "
            "complete instantly and look successful"
        )
    return CampaignPlan(symbols=list(symbols), days=days)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``pips backfill --symbols A,B --from YYYY-MM-DD --to YYYY-MM-DD [--dry-run]``.

    ``--dry-run`` prints the plan and its cost without opening a session. That is the default
    thing to do first: the plan is cheap and a mis-typed range is not.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="pips backfill")
    parser.add_argument("--symbols", required=True, help="comma-separated Breeze stock codes")
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--dry-run", action="store_true", help="cost the plan, fetch nothing")
    parser.add_argument("--calendar", default="config/calendars/nse_equity.yaml")
    parser.add_argument("--data-root", default=None, help="defaults to $PIPS_DATA_ROOT")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        plan = plan_campaign(
            [s.strip() for s in args.symbols.split(",") if s.strip()],
            date.fromisoformat(args.start),
            date.fromisoformat(args.end),
            Path(args.calendar),
        )
    except ValueError as exc:
        print(f"backfill: {exc}")
        return 2

    print(f"backfill plan: {plan.describe()}")

    from pips.data.breeze.budget import CallBudget
    from pips.data.breeze.client import budgeted_fetcher, build_session, default_paths

    bronze, manifest_path, budget_state = default_paths(args.data_root)
    budget = CallBudget.from_config(Path("config/breeze.yaml"), state_path=budget_state)
    print(f"  budget: {budget.remaining} calls remaining today of {budget.effective_budget}")
    if plan.exceeds_budget(budget.remaining):
        print("  NOTE: this plan exceeds today's remaining budget. It will stop cleanly when")
        print("        the budget is spent and resume tomorrow — finished keys cost no calls.")

    if args.dry_run:
        print("  --dry-run: nothing fetched.")
        return 0

    from pips.data.breeze.backfill import run_backfill

    fetcher = budgeted_fetcher(build_session(), budget)
    result = run_backfill(plan.symbols, plan.days, fetcher, bronze, manifest_path)
    print(
        f"  attempted={result.attempted} fetched={result.fetched} empty={result.empty} "
        f"errored={result.errored} skipped={result.skipped}"
    )
    if result.stopped_on_rate_limit:
        print("  STOPPED: rate limited. The vendor rejected us BELOW the configured pace, so")
        print("           the pace is wrong — lower max_calls_per_minute in config/breeze.yaml")
        print("           rather than retrying (ops/runbooks/backfill.md).")
        return 1
    if result.stopped_on_budget:
        print("  STOPPED: daily budget spent. Resume tomorrow; finished keys cost no calls.")
        return 0
    if result.errored:
        print(f"  {result.errored} key(s) errored and were NOT marked done — they retry next run.")
        return 1
    print("  campaign complete.")
    return 0
