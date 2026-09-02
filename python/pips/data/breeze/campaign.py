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
from typing import Final

from pips.core.calendar import SESSION_MINUTES_DEFAULT, load_calendar

__all__ = ["CANDLES_PER_CALL", "SUPPORTED_INTERVALS", "CampaignPlan", "main", "plan_campaign"]

SUPPORTED_INTERVALS: Final = ("1second", "1minute", "5minute", "30minute", "1day")
"""What ``get_historical_data_v2`` serves (blueprint §4.4)."""

_INTERVAL_SECONDS: Final = {"1second": 1, "1minute": 60, "5minute": 300, "30minute": 1800}

CANDLES_PER_CALL: Final = 1000
"""``config/breeze.yaml``\'s ``fetch.candles_per_call``, still ``verified: false``.

A blueprint planning figure. Every cost below scales inversely with it, so it is named here
rather than inlined -- when the M3 probe measures it, one constant moves.
"""


def _candles_per_session(interval: str, session_minutes: int) -> int:
    """Candles one session yields at ``interval``. A day bar is one candle, by definition."""
    if interval == "1day":
        return 1
    seconds = _INTERVAL_SECONDS[interval]
    return -(-session_minutes * 60 // seconds)


@dataclass(frozen=True)
class CampaignPlan:
    """What a campaign will attempt, costed."""

    symbols: list[str]
    days: list[date]
    interval: str = "1minute"
    session_minutes: int = SESSION_MINUTES_DEFAULT
    candles_per_call: int = CANDLES_PER_CALL

    @property
    def candles_per_symbol_day(self) -> int:
        return _candles_per_session(self.interval, self.session_minutes)

    @property
    def calls_per_symbol_day(self) -> int:
        """Calls one symbol-day costs -- at least one, however few candles it returns."""
        return max(1, -(-self.candles_per_symbol_day // self.candles_per_call))

    @property
    def estimated_calls(self) -> int:
        """What THIS code will spend: one call per symbol-day, whatever the interval.

        `budgeted_fetcher` requests `ist_window(day)` -- a single day -- and the manifest and
        bronze layout are keyed per symbol-day, which is what makes a resume granular. So the
        per-day toll is paid whether the reply carries 22,500 candles or one, and a coarse
        interval buys nothing under this shape.

        Costing it any other way is not academic: the seeding plan was written up at 1,800
        calls on the vendor's range allowance and would have spent 1.4 million on this
        fetcher. See `estimated_calls_if_ranged`.
        """
        return len(self.symbols) * len(self.days) * self.calls_per_symbol_day

    @property
    def estimated_calls_if_ranged(self) -> int:
        """What the VENDOR would allow: <=``candles_per_call`` per call over any range.

        Three years of daily bars is 782 candles and therefore one call per symbol. The
        difference between this and :attr:`estimated_calls` is a **fetch shape**, not a quota
        -- and it is the whole cost of a universe-seeding pass. Reported so the gap is a
        number in the plan rather than something rediscovered in prose.
        """
        total = self.candles_per_symbol_day * len(self.days)
        return len(self.symbols) * max(1, -(-total // self.candles_per_call))

    def exceeds_budget(self, daily_budget: int) -> bool:
        return self.estimated_calls > daily_budget

    def describe(self) -> str:
        line = (
            f"{len(self.symbols)} symbols x {len(self.days)} trading days at {self.interval} "
            f"= {self.estimated_calls} calls "
            f"({self.days[0]} to {self.days[-1]})"
        )
        ranged = self.estimated_calls_if_ranged
        if ranged < self.estimated_calls:
            line += (
                f"\n  NOTE: {ranged} calls would serve this range if one call could span days."
                f"\n        This fetcher requests one day per call, so the plan costs"
                f" {self.estimated_calls}."
            )
        return line


def plan_campaign(
    symbols: list[str],
    start: date,
    end: date,
    calendar_path: Path,
    interval: str = "1minute",
) -> CampaignPlan:
    """Enumerate the symbol-days a campaign would fetch.

    Weekends are dropped from the calendar. Exchange holidays are NOT -- the holiday list is
    still unverified (M6 sources it), so a holiday is left in the plan and resolves itself at
    fetch time: Breeze returns an empty reply, the manifest marks it EMPTY, and it is never
    fetched again. Guessing holidays here would risk skipping a real trading day, which is the
    more expensive error.
    """
    if not symbols:
        raise ValueError("a campaign needs at least one symbol")
    if interval not in SUPPORTED_INTERVALS:
        # Not defaulted to 1minute: a typo would then be costed at 1 call per symbol-day where
        # 1second costs 23, and the plan would under-state the spend by 23x.
        raise ValueError(
            f"unsupported interval {interval!r}; get_historical_data_v2 serves "
            f"{', '.join(SUPPORTED_INTERVALS)} (blueprint §4.4)"
        )
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
    return CampaignPlan(
        symbols=list(symbols),
        days=days,
        interval=interval,
        session_minutes=calendar.continuous_session_minutes,
    )


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
    parser.add_argument(
        "--interval",
        default="1minute",
        help=f"one of {', '.join(SUPPORTED_INTERVALS)} (default 1minute)",
    )
    parser.add_argument("--data-root", default=None, help="defaults to $PIPS_DATA_ROOT")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        plan = plan_campaign(
            [s.strip() for s in args.symbols.split(",") if s.strip()],
            date.fromisoformat(args.start),
            date.fromisoformat(args.end),
            Path(args.calendar),
            interval=args.interval,
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

    fetcher = budgeted_fetcher(build_session(), budget, interval=plan.interval)
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
