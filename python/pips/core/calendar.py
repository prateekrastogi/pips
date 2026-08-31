"""Exchange calendar and session structure  [C-SESS-01] (§3.15, ADR-0004).

The calendar answers two different questions and keeps them apart:

* **which day** the exchange trades -- weekday plus a holiday list that is *data*, carrying a
  source and a verification date like any fee schedule (rule 6);
* **which session state** an instant falls in -- and that answer depends on the **broker
  cutoff**, which is per broker x product x instrument x side and arrives from the daily
  capability snapshot. The cutoff is therefore an argument, never a constant. §3.15 is
  explicit that a hard-coded time is wrong, and the reason is practical: brokers move their
  square-off, and a baked constant fails on the day it changes with no test to catch it.

The closing auction (CAS) is modelled as a **separate venue**, not a session state, because
its window overlaps the continuous close in wall-clock time. It is disabled as an alpha venue
(ADR-0004).
"""

from __future__ import annotations

from datetime import date, datetime, time
from enum import StrEnum
from pathlib import Path
from typing import Final

from pydantic import Field

from pips.core.config import PipsConfig, load_yaml
from pips.core.ids import ShortId, content_hash, short_id
from pips.core.time import NS_PER_SECOND, to_ist

__all__ = ["ExchangeCalendar", "SessionState", "load_calendar"]

_UNTRADEABLE: Final = frozenset({"CAS", "FLATTEN_ONLY"})


class SessionState(StrEnum):
    """The six session states of §3.15."""

    OPEN_SHOCK = "OPEN_SHOCK"
    OPEN_DIGEST = "OPEN_DIGEST"
    MID = "MID"
    LATE_CTS = "LATE_CTS"
    CAS = "CAS"
    FLATTEN_ONLY = "FLATTEN_ONLY"

    @property
    def tradeable_as_alpha(self) -> bool:
        """Whether an alpha may open risk in this state.

        ``FLATTEN_ONLY`` is exposure-reducing by definition; ``CAS`` is disabled pending
        auction data and broker support (ADR-0004).
        """
        return self.value not in _UNTRADEABLE


def _parse_clock(text: str) -> time:
    # A wall-clock field, not an instant: a session boundary is "09:15 exchange-local"
    # every day, and attaching a date or a zone here would make it one specific moment.
    return datetime.strptime(text, "%H:%M:%S").time()


class _Window(PipsConfig):
    start: str
    end: str


class _CasWindow(_Window):
    enabled_as_alpha: bool = False


class ExchangeCalendar(PipsConfig):
    """A validated, content-addressed exchange calendar."""

    schema_version: int
    exchange: str
    segment: str
    timezone: str
    continuous_session: _Window
    session_states: dict[str, str]
    cas_window: _CasWindow
    holidays: list[date] = Field(default_factory=list)
    holidays_source: str | None = None
    holidays_verified_on: date | None = None

    # -- identity ---------------------------------------------------------------------
    def content_hash(self) -> str:
        """Calendar hash -- an input to trial identity [C-ID-01] and bundles [C-BNDL-01]."""
        return content_hash(self.model_dump(mode="json"))

    def short_id(self) -> ShortId:
        return short_id(self.content_hash())

    # -- trading days -----------------------------------------------------------------
    @property
    def holidays_verified(self) -> bool:
        """Whether the holiday list has a source and a verification date."""
        return bool(self.holidays_source) and self.holidays_verified_on is not None

    def require_verified_holidays(self) -> None:
        """Refuse to proceed on an unverified calendar.

        Called by anything on the path to real capital. Research on fixtures does not need
        it, which is why an unverified calendar stays usable rather than being fatal at load.
        """
        if not self.holidays_verified:
            raise RuntimeError(
                f"{self.exchange} {self.segment} calendar holidays are not verified "
                "(holidays_source / holidays_verified_on are unset) — source them at M6 "
                "before this calendar is used for anything that trades"
            )

    def is_trading_day(self, day: date) -> bool:
        """Weekday and not a listed holiday. Honest about an unverified list: see above."""
        return day.weekday() < 5 and day not in self.holidays

    # -- session structure ------------------------------------------------------------
    def _clock_of(self, ts_ns: int) -> time:
        return to_ist(ts_ns).time()

    def _boundaries(self) -> list[tuple[time, SessionState]]:
        return sorted(
            ((_parse_clock(v), SessionState(k)) for k, v in self.session_states.items()),
            key=lambda pair: pair[0],
        )

    def session_at(self, ts_ns: int, broker_cutoff_ns: int) -> SessionState | None:
        """Session state of an instant, or ``None`` if outside the continuous session.

        ``broker_cutoff_ns`` is the instant this broker/product stops permitting new
        positions; from it to the close is ``FLATTEN_ONLY``. It comes from the daily
        capability snapshot and is required, so no caller can accidentally get a default.
        """
        clock = self._clock_of(ts_ns)
        open_t = _parse_clock(self.continuous_session.start)
        close_t = _parse_clock(self.continuous_session.end)
        if not (open_t <= clock < close_t):
            return None

        cutoff = self._clock_of(broker_cutoff_ns)
        if not (open_t < cutoff <= close_t):
            raise ValueError(
                f"broker cutoff {cutoff} is outside the continuous session "
                f"{open_t}-{close_t}; a cutoff must come from the capability snapshot"
            )
        if clock >= cutoff:
            return SessionState.FLATTEN_ONLY

        state = SessionState.OPEN_SHOCK
        for boundary, candidate in self._boundaries():
            if clock >= boundary:
                state = candidate
        return state

    # -- the closing auction ----------------------------------------------------------
    @property
    def cas_enabled_as_alpha(self) -> bool:
        """CAS as an alpha venue. False until ADR-0004 is superseded."""
        return self.cas_window.enabled_as_alpha

    def in_cas_window(self, ts_ns: int) -> bool:
        """Whether an instant falls in the closing-auction window (a separate venue)."""
        clock = self._clock_of(ts_ns)
        return _parse_clock(self.cas_window.start) <= clock < _parse_clock(self.cas_window.end)

    def flatten_deadline_ns(self, day_open_ns: int, broker_cutoff_ns: int) -> int:
        """Latest instant an independent flatten scheduler may still be closing positions.

        The engine's own scheduler closes before the earliest broker cutoff; broker
        auto-square-off is a failure path, never the primary exit (§3.14).
        """
        if broker_cutoff_ns <= day_open_ns:
            raise ValueError("broker cutoff must fall after the session open")
        return broker_cutoff_ns - NS_PER_SECOND


def load_calendar(path: Path) -> ExchangeCalendar:
    """Load and validate an exchange calendar from YAML."""
    return ExchangeCalendar.model_validate(load_yaml(path))
