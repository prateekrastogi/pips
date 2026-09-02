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
from pathlib import Path
from typing import Any

from pips.core.atomic import atomic_write_text
from pips.core.locality import refuse_repo_paths
from pips.data.breeze.budget import DailyBudgetExceededError
from pips.data.breeze.ingest import ResponseKind, classify_response

__all__ = ["BackfillResult", "Manifest", "run_backfill"]

Fetcher = Callable[[str, date], Any]

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
        self.outcomes[self.key(symbol, day)] = outcome.value
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

            if kind is ResponseKind.RATE_LIMITED:
                # Stop the whole run. Pushing on would collect more rejections, and marking
                # this key done would record a hole that looks like a holiday forever.
                stopped_rate = True
                break
            if kind is ResponseKind.ERROR:
                errored += 1
                continue  # deliberately NOT marked: the next run retries it

            _write_bronze(bronze_root, symbol, day, payload)
            if kind is ResponseKind.OK:
                fetched += 1
            else:
                empty += 1
            if kind in _TERMINAL:
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
