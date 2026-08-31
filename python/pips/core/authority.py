"""GATE-0 data-use authority  [G-AUTH-0] (§2.1, ADR-0006, ADR-0010).

pips reads market data from ICICI Breeze and places orders through a different broker. That
split is the whole architecture (rule 7), and it is also the thing ICICI has not published a
position on: their public terms describe Breeze as being for personal trading and prohibit
third-party trading integration, and they support self-built code, but there is no explicit
data-only carve-out for signals executed elsewhere. So **before any live order**, either that
question is answered in writing, or the certified signal feed moves to the execution broker's
own entitled feed.

The design point here is that the gate cannot be cleared by editing a boolean. A record that
claims the gate is cleared without the evidence to back it **fails to construct** -- the lie
is inexpressible rather than merely disallowed at the point of use. That matters because this
guard will be consulted exactly once, under pressure, by whoever is trying to go live.
"""

from __future__ import annotations

import sys
from datetime import date
from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from pips.core.config import PipsConfig, load_yaml

__all__ = ["AuthorityRecord", "AuthorityStatus", "SignalFeed", "load_authority", "main"]

# ADR-0010 deferred Zerodha, so the fallback set has exactly one member. If that ever grows
# again it is an ADR, and this constant is where the change lands.
_FALLBACK_FEEDS = ("Flattrade",)


class AuthorityStatus(StrEnum):
    """Where the GATE-0 question stands."""

    UNFILED = "UNFILED"
    FILED_AWAITING_RESPONSE = "FILED_AWAITING_RESPONSE"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    RESOLVED_BY_FEED_SWAP = "RESOLVED_BY_FEED_SWAP"


class SignalFeed(StrEnum):
    """Which feed the certified signal actually comes from."""

    BREEZE = "BREEZE"
    FLATTRADE = "FLATTRADE"


class AuthorityRecord(PipsConfig):
    """The evidence record for `[G-AUTH-0]`, stored beside the feasibility reports."""

    gate: str
    status: AuthorityStatus
    question_ref: str
    filed_on: date | None = None
    response_received_on: date | None = None
    response_summary: str | None = None
    evidence_paths: list[str] = Field(default_factory=list)
    certified_signal_feed: SignalFeed = SignalFeed.BREEZE
    notes: str = ""

    # PipsConfig is strict by design (no silent coercion at a schema boundary), and YAML
    # hands us plain strings. Coerce the two enum fields explicitly rather than relaxing
    # strictness for the whole model: an unknown value must still be a hard error here, not
    # a string that quietly flows through as a status nobody defined.
    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, value: object) -> object:
        return AuthorityStatus(value) if isinstance(value, str) else value

    @field_validator("certified_signal_feed", mode="before")
    @classmethod
    def _coerce_feed(cls, value: object) -> object:
        return SignalFeed(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _a_cleared_gate_must_carry_its_evidence(self) -> AuthorityRecord:
        cleared = {AuthorityStatus.GRANTED, AuthorityStatus.RESOLVED_BY_FEED_SWAP}

        if self.status is AuthorityStatus.UNFILED and (
            self.filed_on or self.response_received_on or self.response_summary
        ):
            raise ValueError(
                "status UNFILED cannot carry a filing date, a response date or a summary"
            )

        if self.status in cleared or self.status is AuthorityStatus.DENIED:
            if self.status is not AuthorityStatus.RESOLVED_BY_FEED_SWAP and self.filed_on is None:
                raise ValueError(f"status {self.status} requires filed_on")
            if self.response_received_on is None:
                raise ValueError(f"status {self.status} requires response_received_on")
            if not self.response_summary:
                raise ValueError(f"status {self.status} requires a response_summary")

        if self.status in cleared and not self.evidence_paths:
            raise ValueError(
                f"status {self.status} requires at least one evidence path — a cleared gate "
                "with no evidence is not a cleared gate (rule 3)"
            )

        if (
            self.status is AuthorityStatus.RESOLVED_BY_FEED_SWAP
            and self.certified_signal_feed is SignalFeed.BREEZE
        ):
            raise ValueError(
                "RESOLVED_BY_FEED_SWAP while certified_signal_feed is BREEZE is a "
                "contradiction: the swap is what resolves the gate"
            )

        if (
            self.filed_on
            and self.response_received_on
            and self.response_received_on < self.filed_on
        ):
            raise ValueError(
                f"response_received_on {self.response_received_on} is before "
                f"filed_on {self.filed_on}"
            )
        return self

    def live_trading_permitted(self) -> bool:
        """Whether `[G-AUTH-0]` permits a live order.

        One of three parts of the live-flag chain (rule 8); the others are the compiled
        ``live`` feature and ``PIPS_LIVE=1``. This one alone is never sufficient.
        """
        return self.status in {AuthorityStatus.GRANTED, AuthorityStatus.RESOLVED_BY_FEED_SWAP}

    def blocking_reason(self) -> str | None:
        """Why live trading is blocked, phrased so the remedy is obvious. ``None`` if clear."""
        fallback = " or ".join(_FALLBACK_FEEDS)
        if self.status is AuthorityStatus.UNFILED:
            return (
                f"[G-AUTH-0] the ICICI data-use question has not been filed. Send the letter "
                f"in {self.question_ref}, then record the filing date here."
            )
        if self.status is AuthorityStatus.FILED_AWAITING_RESPONSE:
            filed = f" (filed {self.filed_on})" if self.filed_on else ""
            return f"[G-AUTH-0] filed and awaiting ICICI's written response{filed}."
        if self.status is AuthorityStatus.DENIED:
            return (
                "[G-AUTH-0] ICICI declined to confirm data-only use. The gate can now be "
                f"cleared only by moving the certified signal feed to {fallback} "
                "(ADR-0006, an adapter swap, not an architecture change) — or, if that "
                "broker's terms do not permit it either, by reopening a second execution "
                "venue (ADR-0010)."
            )
        return None


def load_authority(path: Path) -> AuthorityRecord:
    """Load and validate the GATE-0 record."""
    return AuthorityRecord.model_validate(load_yaml(path))


_RECORD = Path("docs/reports/feasibility/gate0-authority.yaml")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``pips authority check [record.yaml]``.

    Exits 0 when the record is valid, whether or not the gate is cleared — a blocking gate
    is the correct state today, not a build failure. Exit 1 means the record is missing or
    malformed, which IS a failure: an unreadable gate is an unenforced one.
    """
    args = list(argv if argv is not None else sys.argv[1:])
    path = Path(args[0]) if args else _RECORD
    try:
        record = load_authority(path)
    except (OSError, ValueError) as exc:
        print(f"authority-check FAILED: {path} is missing or malformed\n  {exc}")
        return 1

    print(f"[{record.gate}] status={record.status.value} feed={record.certified_signal_feed.value}")
    if record.live_trading_permitted():
        print("  live trading: PERMITTED by this gate")
        print("  (still gated by the rest of the live-flag chain: `live` feature, PIPS_LIVE=1,")
        print("   and i_understand_live_trading: true — rule 8)")
    else:
        print("  live trading: BLOCKED")
        print(f"  {record.blocking_reason()}")
    return 0
