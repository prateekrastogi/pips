"""Live Breeze wiring: session, budgeted fetcher, campaign entry point  (§6 M4).

Deliberately thin. Everything with a decision in it -- response classification, normalization,
budgeting, the manifest -- is tested against cassettes and fakes elsewhere. What lives here is
the part that cannot be tested without a network, so there is as little of it as possible.

**Ported from SAL-0001** for the session flow: the token is interactive and DAILY, obtained by
logging in at the portal and copying `API_Session` from the redirect. Only API *calls* must
egress from the whitelisted IP -- the browser login can happen anywhere, which is why the
runbook has a human on a laptop and the fetch on arb-vm.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from pips.data.breeze.budget import CallBudget
from pips.data.breeze.probe import ist_range, ist_window

__all__ = [
    "budgeted_fetcher",
    "build_session",
    "ranged_fetcher",
]


def build_session(api_key: str | None = None) -> Any:
    """A session-generated BreezeConnect from the environment.

    Imported lazily so the rest of the package -- and every test -- works without the vendor
    SDK installed. CI never reaches this function.
    """
    from breeze_connect import BreezeConnect

    client = BreezeConnect(api_key=api_key or os.environ["BREEZE_API_KEY"])
    client.generate_session(
        api_secret=os.environ["BREEZE_API_SECRET"],
        session_token=os.environ["BREEZE_SESSION_TOKEN"],
    )
    return client


def budgeted_fetcher(
    client: Any,
    budget: CallBudget,
    exchange: str = "NSE",
    product: str = "cash",
    interval: str = "1minute",
) -> Callable[[str, date], Any]:
    """A fetcher for :func:`~pips.data.breeze.backfill.run_backfill`, paced by ``budget``.

    The window is IST wall-clock via :func:`ist_window` -- SAL-0002's hardest-won fact is that
    Breeze ignores the trailing ``Z`` and silently CLIPS a UTC window rather than erroring.
    """

    def fetch(symbol: str, day: date) -> Any:
        budget.acquire()  # raises DailyBudgetExceededError, which the campaign stops on
        frm, to = ist_window(day)
        return client.get_historical_data_v2(
            interval=interval,
            from_date=frm,
            to_date=to,
            stock_code=symbol,
            exchange_code=exchange,
            product_type=product,
        )

    return fetch


def ranged_fetcher(
    client: Any,
    budget: CallBudget,
    exchange: str = "NSE",
    product: str = "cash",
    interval: str = "1day",
) -> Callable[[str, date, date], Any]:
    """A fetcher for :func:`~pips.data.breeze.backfill.run_range_backfill`.

    One call per SYMBOL rather than per symbol-day, and therefore one `budget.acquire()`. That
    is the whole economics of a universe seed: three years of daily bars is 782 candles, inside
    the vendor's 1,000-per-call allowance, so a range request costs one call where the per-day
    fetcher costs 782 and returns one candle for each of them.

    Pacing still applies. The per-minute limit counts calls, not candles, so a range fetch is
    paced exactly as a day fetch is.

    The window comes from :func:`ist_range`, whose multi-day span is **unverified against the
    live API** -- `ist_window` exists because Breeze silently CLIPS a UTC window rather than
    erroring, and nobody has yet asked it for three years in one request.
    """

    def fetch(symbol: str, start: date, end: date) -> Any:
        budget.acquire()  # raises DailyBudgetExceededError, which the range run stops on
        frm, to = ist_range(start, end)
        return client.get_historical_data_v2(
            interval=interval,
            from_date=frm,
            to_date=to,
            stock_code=symbol,
            exchange_code=exchange,
            product_type=product,
        )

    return fetch


def default_paths(data_root: str | None = None) -> tuple[Path, Path, Path]:
    """``(bronze, manifest, budget_state)`` under the VM data root (rule 14)."""
    root = Path(data_root or os.environ.get("PIPS_DATA_ROOT", "/srv/pips"))
    return (
        root / "bronze",
        root / "state" / "backfill-manifest.json",
        root / "state" / "budget.json",
    )
