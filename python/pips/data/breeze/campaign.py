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

__all__ = [
    "CANDLES_PER_CALL",
    "SUPPORTED_INTERVALS",
    "CampaignPlan",
    "RangeTooFineError",
    "chunk_range",
    "main",
    "plan_campaign",
]

SUPPORTED_INTERVALS: Final = ("1second", "1minute", "5minute", "30minute", "1day")
"""What ``get_historical_data_v2`` serves (blueprint §4.4)."""

_INTERVAL_SECONDS: Final = {"1second": 1, "1minute": 60, "5minute": 300, "30minute": 1800}

CANDLES_PER_CALL: Final = 1000
"""The vendor's per-call ceiling, and it truncates rather than erroring at it.

MEASURED 2026-09-03, one authorised call: asked for three days of 1-minute bars from 09:15 and
got exactly 1,000 candles beginning at 11:07 the same morning -- 1,125 requested, and the OLDEST
125 simply absent, under Status 200 with no Error. The same failure shape as the UTC window
`ist_window` exists for: missing bars rather than a failure.

Three years of DAILY bars came back whole in one call (742 candles), which is what makes a
universe seed one call per symbol.

**Defined once, here, and imported by `backfill`.** It was defined in both, at the same value,
which is a drift waiting to happen: this module splits ranges so no reply can reach the cap and
that one refuses a reply that does. Move one and the planner builds chunks the fetcher rejects,
or -- worse -- chunks that truncate and the fetcher accepts, which is silent. The probe measured
this number once, so one definition carries it.
"""


def _candles_per_session(interval: str, session_minutes: int) -> int:
    """Candles one session yields at ``interval``. A day bar is one candle, by definition."""
    if interval == "1day":
        return 1
    seconds = _INTERVAL_SECONDS[interval]
    return -(-session_minutes * 60 // seconds)


class RangeTooFineError(ValueError):
    """No arrangement of whole days fits one call at this interval.

    Distinct from every other bad argument so a caller can tell the one recoverable case --
    fall back to the per-symbol-day campaign -- from a typo it should surface instead.
    """


def chunk_range(
    start: date,
    end: date,
    interval: str,
    *,
    session_minutes: int = SESSION_MINUTES_DEFAULT,
    candles_per_call: int = CANDLES_PER_CALL,
) -> list[tuple[date, date]]:
    """Split ``start``..``end`` into ranges no single call can truncate.

    The 2026-09-03 probe measured the limit: Breeze caps a reply at ``candles_per_call`` and
    drops the OLDEST bars to fit, under Status 200 with no Error. `run_range_backfill` refuses
    a reply that arrives at the cap; this is what keeps one from arriving.

    **The count is deliberately an over-estimate.** Weekends are free, holidays are not
    subtracted (the list is unverified -- an open M6 item), and Breeze omits untraded bars, so
    a chunk is planned for more candles than it can return. Each of those errs toward a smaller
    chunk, costing an extra call and never losing a bar. The opposite error is silent: a chunk
    that reaches the cap loses the beginning of the period it asked for and reports success.

    Weekdays rather than calendar days, because counting calendar days would buy about 40% more
    calls than the data needs -- and would split three years of daily bars, which the probe
    measured fitting in one.

    Every chunk is planned STRICTLY below the cap. `run_range_backfill` refuses a reply that
    arrives at it, there being no way to tell a full call from a clipped one, so a chunk planned
    to land exactly on the cap is one the fetcher rejects -- a campaign priced for a seed it
    cannot run, failing one call into a three-year backfill.
    """
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    if interval not in SUPPORTED_INTERVALS:
        raise ValueError(f"interval {interval!r} is not one of {list(SUPPORTED_INTERVALS)}")

    per_session = _candles_per_session(interval, session_minutes)
    # `>=`, not `>`: `run_range_backfill` refuses a reply that arrives AT the cap, because a
    # full call and a clipped one are indistinguishable. A session that exactly fills a call
    # therefore has no fetchable range either -- one day is the smallest range there is.
    if per_session >= candles_per_call:
        # No arrangement of whole days fits. Chunking to one day anyway would return a reply at
        # the cap and lose the morning -- the exact failure the refusal exists to prevent. The
        # ranged shape does not exist at this interval; the per-symbol-day campaign serves it.
        raise RangeTooFineError(
            f"one session at {interval} is {per_session} candles, more than the "
            f"{candles_per_call} a single call returns, so no range of whole days can be "
            f"fetched without truncation -- use the per-symbol-day campaign for this interval"
        )

    chunks: list[tuple[date, date]] = []
    chunk_start, candles, day = start, 0, start
    while day <= end:
        cost = per_session if day.weekday() < 5 else 0
        if candles + cost >= candles_per_call:
            # Close BEFORE this day: `cost <= candles_per_call` is guaranteed above, so the
            # chunk being closed always holds at least one day and the walk cannot stall.
            chunks.append((chunk_start, day - timedelta(days=1)))
            chunk_start, candles = day, 0
        candles += cost
        day += timedelta(days=1)
    chunks.append((chunk_start, end))
    return chunks


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

    @property
    def estimated_calls_if_chunked(self) -> int | None:
        """What a DAY-ALIGNED ranged fetch costs -- the number this code would actually spend.

        Between the other two, and different from both. :attr:`estimated_calls` is the
        per-symbol-day toll; :attr:`estimated_calls_if_ranged` is the vendor's allowance, which
        assumes windows packed to exactly ``candles_per_call`` and therefore ending mid-session.
        The bronze layout is keyed per day, so a chunk stops at a day boundary and wastes
        whatever is left of the cap. For U300 over three years at 1m that gap is 88,200 against
        117,600 -- the allowance understates the real cost by a third.

        ``None`` when no arrangement of whole days fits a call (1-second yields 22,500 candles a
        session). Not a number, because every number would be a claim that some ranged fetch is
        possible, and quoting a price for a shape that does not exist is how this estimate went
        wrong the first time.
        """
        if not self.days:
            return 0
        try:
            chunks = chunk_range(
                self.days[0],
                self.days[-1],
                self.interval,
                session_minutes=self.session_minutes,
                candles_per_call=self.candles_per_call,
            )
        except RangeTooFineError:
            # Only this one. A bad interval or a backwards range is a different fact, and
            # reporting it as "no ranged shape exists" would cost a typo its only symptom.
            return None
        return len(self.symbols) * len(chunks)

    def exceeds_budget(self, daily_budget: int) -> bool:
        return self.estimated_calls > daily_budget

    def describe(self) -> str:
        line = (
            f"{len(self.symbols)} symbols x {len(self.days)} trading days at {self.interval} "
            f"= {self.estimated_calls} calls "
            f"({self.days[0]} to {self.days[-1]})"
        )
        chunked = self.estimated_calls_if_chunked
        if chunked is not None and chunked < self.estimated_calls:
            # The ACHIEVABLE alternative, and the flag that delivers it. This used to advertise
            # `estimated_calls_if_ranged` -- the vendor's allowance, which needs windows ending
            # mid-session while the bronze layout is keyed per day -- and to say "this fetcher
            # requests one day per call", which stopped being true when the chunker landed.
            # Naming a number no code path can reach, beside a capability the note denied, is
            # two ways of misleading whoever is deciding what to spend.
            line += (
                f"\n  NOTE: --ranged would serve this range in {chunked} calls, day-aligned"
                f"\n        chunks that cannot truncate, against {self.estimated_calls} here."
                f"\n        The vendor would allow {self.estimated_calls_if_ranged} with"
                f" mid-session windows, which this layout does not use."
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
    parser.add_argument(
        "--ranged",
        action="store_true",
        help="fetch day-aligned chunks spanning many sessions instead of one call per "
        "symbol-day; far cheaper, and a DIFFERENT manifest grain",
    )
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

    from pips.data.breeze import backfill as backfill_module
    from pips.data.breeze import client as client_module

    if args.ranged:
        # SWITCHING GRAIN IS NOT FREE. Per-symbol-day keys are `SYMBOL:YYYY-MM-DD`; range keys
        # are `SYMBOL:INTERVAL:START:END`. A ranged run matches none of the former, so days
        # already fetched are fetched again at full price while the manifest still says they
        # were done. Not refused -- switching shapes is a legitimate thing to want -- but doing
        # it by accident costs a second campaign, so it is said out loud.
        existing = backfill_module.Manifest.load(manifest_path)
        stale = [
            k
            for k in existing.outcomes
            if k.count(":") == 1 and k.split(":")[0] in set(plan.symbols)
        ]
        if stale:
            print(
                f"  NOTE: the manifest holds {len(stale)} symbol-day key(s) for these symbols."
                f"\n        A ranged run keys on symbol:interval:start:end, so those days are"
                f"\n        re-fetched at full price. Finish per-day, or accept the re-fetch."
            )
        result = backfill_module.run_range_backfill(
            plan.symbols,
            plan.days[0],
            plan.days[-1],
            plan.interval,
            client_module.ranged_fetcher(
                client_module.build_session(), budget, interval=plan.interval
            ),
            bronze,
            manifest_path,
        )
    else:
        fetcher = budgeted_fetcher(build_session(), budget, interval=plan.interval)
        result = backfill_module.run_backfill(
            plan.symbols, plan.days, fetcher, bronze, manifest_path
        )
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
