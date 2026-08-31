"""Market-hours restart guard for the arb-vm deploy rail  [C-DEPLOY-01] (§2.2).

The rail rolls research and data services on every main update. **Trading-path services never
hot-swap during market hours**: their restart is held until after the close or before the
open, unless a human forces it — and a forced intraday restart still follows the crash
recovery path (journal replay, then broker reconciliation, §3.13).

**This guard fails closed, deliberately.** Ported from SAL-0010, whose equivalent guard was
inert in exactly the way that matters: it ran ``pgrep`` inside a container with no ``procps``,
the command exited 127, and the caller read the failure as "not busy". A guard whose whole
purpose is to avoid restarting mid-trade quietly did nothing, and looked healthy doing it. So
here every uncertainty resolves to *defer*: an unknown service is trading-path, and an absent
calendar blocks. Being wrong this way costs one deferred deploy cycle; being wrong the other
way restarts the order plane mid-session.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pips.core.calendar import ExchangeCalendar
from pips.core.time import to_ist

__all__ = [
    "ROLLING_SERVICES",
    "TRADING_PATH_SERVICES",
    "RestartDecision",
    "main",
    "restart_decision",
]

# §2.2. Anything not named here is treated as trading-path — see the fail-closed note above.
TRADING_PATH_SERVICES: Final[frozenset[str]] = frozenset(
    {"breeze-reader", "shadow-engine", "live-engine"}
)
ROLLING_SERVICES: Final[frozenset[str]] = frozenset(
    {"research", "research-runner", "backfill", "telemetry"}
)

# The protected window, wider than the continuous session at both ends on purpose: a reader
# that must be warm at 09:15 cannot be restarting at 09:10, and the closing auction runs to
# 15:35 (§3.15) even though the continuous tape stops at 15:30.
_WINDOW_OPEN: Final = "08:45"
_WINDOW_CLOSE: Final = "15:35"


@dataclass(frozen=True)
class RestartDecision:
    """Whether the rail may restart a service now, and why."""

    permitted: bool
    reason: str


def restart_decision(
    service: str,
    now_ns: int,
    calendar: ExchangeCalendar | None,
    *,
    force: bool = False,
) -> RestartDecision:
    """Decide whether ``service`` may be restarted at ``now_ns``."""
    if force:
        return RestartDecision(
            True,
            f"{service}: restart FORCED by a human. §2.2 requires a forced intraday restart "
            "to follow the crash-recovery path like any other — journal replay, then broker "
            "reconciliation, before any new risk is admitted (§3.13).",
        )

    if service in ROLLING_SERVICES:
        return RestartDecision(
            True, f"{service}: research/data service, rolls on every main update (§2.2)."
        )

    classification = (
        "trading-path service"
        if service in TRADING_PATH_SERVICES
        else "UNKNOWN service, treated as trading-path (fail closed)"
    )

    if calendar is None:
        return RestartDecision(
            False,
            f"{service}: no calendar available, so market hours cannot be determined. "
            "Deferring — if we cannot tell whether it is market hours, it is market hours.",
        )

    now = to_ist(now_ns)
    if not calendar.is_trading_day(now.date()):
        return RestartDecision(
            True,
            f"{service}: {now.date()} is not a trading day on the {calendar.exchange} calendar.",
        )

    clock = now.strftime("%H:%M")
    if _WINDOW_OPEN <= clock < _WINDOW_CLOSE:
        return RestartDecision(
            False,
            f"{service}: {classification}; {clock} IST is inside the protected window "
            f"{_WINDOW_OPEN}-{_WINDOW_CLOSE} on a trading day. Held until {_WINDOW_CLOSE} "
            "(§2.2). A human may force it, which then follows the crash-recovery path.",
        )

    return RestartDecision(
        True,
        f"{service}: {classification}; {clock} IST is outside the protected window "
        f"{_WINDOW_OPEN}-{_WINDOW_CLOSE}.",
    )


_CALENDAR = Path("config/calendars/nse_equity.yaml")


def main(argv: list[str] | None = None) -> int:
    """CLI: ``pips deploy guard <service> [--force] [--now <iso>]``.

    Exit 0 = the rail may restart this service; exit 1 = defer. ``sync.sh`` reads the exit
    code, so a crash in here must not read as permission: any unexpected failure is caught
    and turned into a deferral, matching the fail-closed rule the module is built around.
    """
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print("usage: pips deploy guard <service> [--force] [--now <iso8601>]", file=sys.stderr)
        return 2

    service = args[0]
    force = "--force" in args
    now_iso: str | None = None
    if "--now" in args:
        now_iso = args[args.index("--now") + 1]

    try:
        from pips.core.time import ts_from_iso

        now_ns = ts_from_iso(now_iso) if now_iso else _now_ns()
        calendar: ExchangeCalendar | None
        try:
            from pips.core.calendar import load_calendar

            calendar = load_calendar(_CALENDAR)
        except (OSError, ValueError) as exc:
            print(f"deploy-guard: calendar unreadable ({exc})")
            calendar = None
        decision = restart_decision(service, now_ns, calendar, force=force)
    except Exception as exc:
        print(f"deploy-guard: DEFER — guard itself failed ({exc!r}); failing closed")
        return 1

    print(f"deploy-guard: {'ALLOW' if decision.permitted else 'DEFER'} — {decision.reason}")
    return 0 if decision.permitted else 1


def _now_ns() -> int:
    import time as _time

    return int(_time.time() * 1_000_000_000)
