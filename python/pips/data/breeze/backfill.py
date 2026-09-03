"""Backfill orchestrator  (§6 M4, ported from SAL-0004).

Per key -- one symbol on one trading day -- fetch, classify, write bronze, and mark the key in
a persisted manifest so a restart costs **zero calls** for work already finished.

The donor's best idea is what it refuses to mark done: a transient error is never marked, so
the next run retries it. pips draws one further distinction the donor could not, because the
classification work at M4 made it available:

===================  ============  ====================================================
outcome              marked done?  why
===================  ============  ====================================================
data returned        yes           the work is finished
empty (holiday)      yes           attempted, and there is genuinely nothing -- an answer
transient error      no            retry next run
**rate limited**     **no**        Breeze sends this as HTTP 200 with an empty body
===================  ============  ====================================================

That last row is the one that matters. A backfill which marks a rate-limited window
"done, no data" writes a permanent hole into the archive that no later QC can tell apart from
a quiet market -- and unlike a crash, it leaves nothing to notice.

Bronze is raw and append-only (§3.4): the exact payload, a receive timestamp, and the request
that produced it. Cleaning happens downstream, because a bronze record that has been cleaned
leaves nowhere to check the cleaning against.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from pips.core.atomic import atomic_write_text
from pips.core.locality import refuse_repo_paths
from pips.data.breeze.budget import DailyBudgetExceededError
from pips.data.breeze.campaign import CANDLES_PER_CALL, chunk_range
from pips.data.breeze.ingest import ResponseKind, classify_response

__all__ = [
    "CANDLES_PER_CALL",
    "BackfillResult",
    "Manifest",
    "RangeTruncatedError",
    "run_backfill",
    "run_range_backfill",
]

Fetcher = Callable[[str, date], Any]
RangeFetcher = Callable[[str, date, date], Any]


class RangeTruncatedError(RuntimeError):
    """A range reply sat exactly on the candle cap, so the oldest bars are probably missing.

    Raised rather than retried: the same range truncates identically next time, so there is
    nothing to retry -- the range itself is too wide for its interval and narrowing it is the
    caller's choice. Raised rather than marked, because a truncated range recorded as done is a
    hole at the START of the window that no later QC can tell from a quiet market.

    A range that genuinely holds exactly the cap is indistinguishable from one that was cut, and
    this refuses both rather than guessing which it has.
    """


class _Decision(StrEnum):
    """What one reply means for the run -- the module docstring's table, as code.

    In one place because there are now two fetch shapes, per symbol-day and per range, and two
    copies of this table would be two places for it to drift with only one under test.
    """

    STORE = "STORE"  # an answer: write bronze, mark done
    RETRY = "RETRY"  # no answer: write nothing, mark nothing, keep going
    STOP = "STOP"  # the vendor refused us: write nothing, mark nothing, end the run


def _decide(kind: ResponseKind) -> _Decision:
    """RETRY is the default, and that is the safety property.

    A fifth `ResponseKind` added later lands here rather than on STORE, so an outcome nobody has
    taught this module about is retried rather than marked done. Unmarked costs a call; marked
    wrongly costs a permanent hole that reads as a holiday.
    """
    if kind is ResponseKind.RATE_LIMITED:
        return _Decision.STOP
    if kind in _TERMINAL:
        return _Decision.STORE
    return _Decision.RETRY


# Outcomes that mean "attempted, and we have our answer". Everything else is pending.
#
# Always true where it is tested, today: RATE_LIMITED breaks out of the run and ERROR
# continues past the mark, so only OK and EMPTY ever reach it. Kept anyway, and not as
# decoration -- it is the safety net for a fifth ResponseKind, which would otherwise fall
# through and be marked done. Unmarked is the safe default: the next run retries.
_TERMINAL = {ResponseKind.OK, ResponseKind.EMPTY}


@dataclass
class Manifest:
    """Which keys are finished, and how each finished.

    "Done" alone cannot distinguish a day with data from a holiday, and a later reader needs
    that to tell a real gap from an empty one -- so the outcome is recorded, not just the fact.
    """

    path: Path
    outcomes: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def key(symbol: str, day: date) -> str:
        return f"{symbol}:{day.isoformat()}"

    @staticmethod
    def range_key(symbol: str, interval: str, start: date, end: date) -> str:
        """A range's key carries its INTERVAL as well as its span.

        Without both, a daily seed would mark a 1-second seed done over the same dates and the
        archive would hold neither while the manifest claimed both.
        """
        return f"{symbol}:{interval}:{start.isoformat()}:{end.isoformat()}"

    def is_done_range(self, symbol: str, interval: str, start: date, end: date) -> bool:
        return self.range_key(symbol, interval, start, end) in self.outcomes

    def mark_range(
        self, symbol: str, interval: str, start: date, end: date, outcome: ResponseKind
    ) -> None:
        self._write(self.range_key(symbol, interval, start, end), outcome)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls(path=path)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # An unreadable manifest means we do not know what is done. Starting from empty
            # re-fetches, which costs budget; assuming everything is done would leave silent
            # holes. Cost is the better failure.
            return cls(path=path)
        return cls(path=path, outcomes=dict(loaded.get("outcomes", {})))

    def is_done(self, symbol: str, day: date) -> bool:
        return self.key(symbol, day) in self.outcomes

    def outcome(self, symbol: str, day: date) -> str | None:
        return self.outcomes.get(self.key(symbol, day))

    def mark(self, symbol: str, day: date, outcome: ResponseKind) -> None:
        self._write(self.key(symbol, day), outcome)

    def _write(self, key: str, outcome: ResponseKind) -> None:
        self.outcomes[key] = outcome.value
        # ATOMIC: this file is rewritten once per key -- 234,900 times on the 3y x U300
        # campaign -- and a truncated manifest sends `load` back to empty, so the restart that
        # was supposed to cost zero calls re-fetches everything already paid for.
        atomic_write_text(
            self.path, json.dumps({"outcomes": self.outcomes}, indent=1, sort_keys=True) + "\n"
        )


@dataclass(frozen=True)
class BackfillResult:
    """What one campaign run did, and why it stopped."""

    attempted: int
    fetched: int
    empty: int
    errored: int
    skipped: int
    stopped_on_budget: bool
    stopped_on_rate_limit: bool

    @property
    def complete(self) -> bool:
        return not (self.stopped_on_budget or self.stopped_on_rate_limit or self.errored)


def _write_bronze(root: Path, symbol: str, day: date, payload: Any) -> Path:
    """Append one raw observation. Never overwrites -- a second look is a new record."""
    directory = root / symbol / day.isoformat()
    directory.mkdir(parents=True, exist_ok=True)
    received = time.time_ns()
    path = directory / f"{received}.json"
    path.write_text(
        json.dumps(
            {
                "request": {"symbol": symbol, "trade_date": day.isoformat(), "interval": "1minute"},
                "received_at_ns": received,
                "payload": payload,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _at_the_cap(payload: Any) -> bool:
    """Whether a reply carries exactly the per-call ceiling, and is therefore suspect."""
    rows = payload.get("Success") if isinstance(payload, dict) else None
    return isinstance(rows, list) and len(rows) >= CANDLES_PER_CALL


def _write_range_bronze(
    root: Path, symbol: str, interval: str, start: date, end: date, payload: Any
) -> Path:
    """One raw observation covering a SPAN of sessions.

    Laid out under the interval so it cannot collide with the per-day tree, and its request
    block carries `from`/`to` rather than `trade_date` -- there is no single trading day to
    name. `promote_bronze` quarantines a shape it cannot read rather than raising over it,
    which is what lets both trees share one bronze root.
    """
    directory = root / symbol / interval / f"{start.isoformat()}_{end.isoformat()}"
    directory.mkdir(parents=True, exist_ok=True)
    received = time.time_ns()
    path = directory / f"{received}.json"
    atomic_write_text(
        path,
        json.dumps(
            {
                "request": {
                    "symbol": symbol,
                    "interval": interval,
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                },
                "received_at_ns": received,
                "payload": payload,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n",
    )
    return path


def run_backfill(
    symbols: list[str],
    days: list[date],
    fetcher: Fetcher,
    bronze_root: Path,
    manifest_path: Path,
) -> BackfillResult:
    """Fetch every unfinished (symbol, day) key, writing bronze and updating the manifest."""
    refuse_repo_paths(bronze_root, what="bronze")
    manifest = Manifest.load(manifest_path)

    attempted = fetched = empty = errored = skipped = 0
    stopped_budget = stopped_rate = False

    for day in days:
        for symbol in symbols:
            if manifest.is_done(symbol, day):
                skipped += 1
                continue
            try:
                payload = fetcher(symbol, day)
            except DailyBudgetExceededError:
                # A clean stop, not a failure: everything finished so far stays finished and
                # the next run picks up exactly where this one left off.
                stopped_budget = True
                break

            attempted += 1
            kind = classify_response(payload)

            decision = _decide(kind)
            if decision is _Decision.STOP:
                # Pushing on would collect more rejections, and marking this key done would
                # record a hole that looks like a holiday forever.
                stopped_rate = True
                break
            if decision is _Decision.RETRY:
                errored += 1
                continue  # deliberately NOT marked: the next run retries it

            _write_bronze(bronze_root, symbol, day, payload)
            if kind is ResponseKind.OK:
                fetched += 1
            else:
                empty += 1
            manifest.mark(symbol, day, kind)
        if stopped_budget or stopped_rate:
            break

    return BackfillResult(
        attempted=attempted,
        fetched=fetched,
        empty=empty,
        errored=errored,
        skipped=skipped,
        stopped_on_budget=stopped_budget,
        stopped_on_rate_limit=stopped_rate,
    )


def run_range_backfill(
    symbols: list[str],
    start: date,
    end: date,
    interval: str,
    fetcher: RangeFetcher,
    bronze_root: Path,
    manifest_path: Path,
) -> BackfillResult:
    """As few calls per symbol as the cap allows, over a range split so none can truncate.

    The per-symbol-day campaign pays the per-day toll whatever the interval -- three years of
    daily bars costs 782 calls per symbol and returns one candle for each. The vendor allows
    <=:data:`CANDLES_PER_CALL` candles over an arbitrary range, which makes the same three
    years ONE call, and 1-minute over three years 391 rather than 782.

    :func:`~pips.data.breeze.campaign.chunk_range` decides the split, and an interval with no
    ranged shape at all (1-second yields 22,500 candles a session) is REFUSED before a call is
    spent, naming the per-symbol-day campaign instead.

    **Resume is per symbol-CHUNK**, which is what the split buys. A three-year 1-minute seed is
    391 calls per symbol; before chunking there was nothing to resume, because the whole range
    could not be fetched at all. Now a run that dies on call 200 costs 200, and a rerun
    re-fetches only what has no answer yet.

    **The multi-day window was measured on 2026-09-03** under a one-call-per-symbol
    authorisation: a three-year daily request returned 742 candles in one call, so the vendor
    honours the range. The same probe found the limit -- a reply is capped at
    :data:`CANDLES_PER_CALL` and the OLDEST bars are dropped to fit, under Status 200 with no
    Error -- which is why a reply arriving at the cap is refused here rather than stored, and
    why anything finer than daily must be split first. :func:`~pips.data.breeze.campaign.
    chunk_range` is what splits it.
    """
    refuse_repo_paths(bronze_root, what="bronze")
    if end < start:
        raise ValueError(f"end {end} is before start {start}")
    # Before the manifest and before any call: an interval with no ranged shape is refused
    # rather than attempted, because the attempt would come back at the cap and lose the
    # morning. The chunks do not depend on the symbol, so they are computed once.
    chunks = chunk_range(start, end, interval)
    manifest = Manifest.load(manifest_path)

    attempted = fetched = empty = errored = skipped = 0
    stopped_budget = stopped_rate = False

    for symbol in symbols:
        for chunk_start, chunk_end in chunks:
            if manifest.is_done_range(symbol, interval, chunk_start, chunk_end):
                skipped += 1
                continue
            try:
                payload = fetcher(symbol, chunk_start, chunk_end)
            except DailyBudgetExceededError:
                stopped_budget = True
                break

            attempted += 1
            kind = classify_response(payload)
            # `kind is OK` is equivalent in practice -- a rate-limited or errored reply carries
            # `Success: None`, so the row count is never at the cap -- and is kept because a
            # row count only means anything on a reply that carried rows.
            if kind is ResponseKind.OK and _at_the_cap(payload):
                raise RangeTruncatedError(
                    f"{symbol} {interval} {chunk_start}..{chunk_end} returned exactly "
                    f"{CANDLES_PER_CALL} candles, the vendor's cap, so the oldest bars in the "
                    "window are probably missing -- under Status 200 with no Error. This range "
                    "was CHUNKED to stay below the cap, so reaching it means the split is "
                    "wrong, not the request: the session length or the cap itself has moved "
                    "from what `chunk_range` assumes. Retrying will truncate identically."
                )
            decision = _decide(kind)
            if decision is _Decision.STOP:
                stopped_rate = True
                break
            if decision is _Decision.RETRY:
                errored += 1
                continue

            _write_range_bronze(bronze_root, symbol, interval, chunk_start, chunk_end, payload)
            if kind is ResponseKind.OK:
                fetched += 1
            else:
                empty += 1
            manifest.mark_range(symbol, interval, chunk_start, chunk_end, kind)

        if stopped_budget or stopped_rate:
            # Both loops. Continuing to the next symbol would spend calls the budget has
            # already refused -- one per symbol -- and report them as errors rather than as
            # the stop they are.
            break

    return BackfillResult(
        attempted=attempted,
        fetched=fetched,
        empty=empty,
        errored=errored,
        skipped=skipped,
        stopped_on_budget=stopped_budget,
        stopped_on_rate_limit=stopped_rate,
    )
