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
    "EGRESS_ENV",
    "VendorEgressError",
    "budgeted_fetcher",
    "build_session",
    "ranged_fetcher",
]


EGRESS_ENV = "PIPS_VENDOR_EGRESS"
"""Names the host whose IP ICICI has whitelisted. Set in `docker-compose.yml`, so it is present
inside the services that run on arb-vm and absent everywhere else."""


class VendorEgressError(RuntimeError):
    """A vendor API call was attempted from a host the vendor does not whitelist."""


def _require_whitelisted_egress() -> None:
    """Refuse a vendor call that would leave from the wrong address.

    ICICI whitelists ONE IP for API calls and it is arb-vm's. A call made from anywhere else
    reaches the vendor from an address it does not know, and the reply is an AUTH-SHAPED failure
    -- which sends the reader to rotate a session token that was never the problem. The wrong
    diagnosis is the cost here, not the failed call.

    Only API *calls* need this. The interactive login that mints the daily token is a browser
    session and may happen anywhere (SAL-0001), which is why the runbook has a human on a laptop
    and the fetch on the VM.

    A guard against ACCIDENT, not an attacker: anything that can set an environment variable can
    pass it. Its job is to make rule 14's data-on-the-VM discipline something the code keeps
    rather than something a person has to remember at the moment they are busiest.
    """
    if os.environ.get(EGRESS_ENV, "").strip():
        return
    raise VendorEgressError(
        f"refusing to open a Breeze session: {EGRESS_ENV} is unset, so this process is not "
        "running on the host whose IP ICICI whitelists. Only arb-vm's address is whitelisted, "
        "and a call from anywhere else fails at the vendor with an auth-shaped error that reads "
        "like a bad token. Run data work on arb-vm (rule 14). Obtaining the daily token in a "
        "browser is exempt and can be done from any machine."
    )


def build_session(api_key: str | None = None) -> Any:
    """A session-generated BreezeConnect from the environment.

    Imported lazily so the rest of the package -- and every test -- works without the vendor
    SDK installed. CI never reaches this function.

    The egress check comes FIRST, before the credentials are read: on a laptop the key is usually
    missing too, and `KeyError: 'BREEZE_API_KEY'` describes the wrong fault.
    """
    _require_whitelisted_egress()

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
