"""Point-in-time corporate-action master  [C-DATA-01] (§6 M6, §3.4, rule 12 causality).

**Shape ported from SAL-0016** (`convexity 790d7235b202:
src/convexity/breakout/data/corporate_actions.py`, deleted from HEAD, 2268 bytes). What that
donor contributes is one good idea: back-adjust a multiplicative factor onto the bars before
an ex-date so the action bar is not a fabricated breakout. Everything else had to be rebuilt —
it is US equities in float arithmetic, with no knowledge time and no causality rule, applying
every supplied action to every pre-ex-date bar regardless of when the action was known or
whether its ex-date had arrived. The salvage row said as much: *a starting point, not a donor
that closes the need.*

**The causality rule is the substance.** Adjusting a bar at ``bar_on``, as of decision time
``as_of``, uses actions where ``bar_on < ex_date <= as_of`` and ``known_from <= as_of``. Both
bounds do work:

``ex_date <= as_of``
    A split announced in June and effective in July must not adjust May bars for a decision
    made in June. The June price has not split; adjusting the trailing window puts the history
    on a different scale from the price being traded, and a 20-day return comes out wrong by
    the split factor — in the flattering direction, because the series looks like it rose.

``known_from <= as_of``
    Ordinary F_t-measurability. Revisions and cancellations arrive late and must not reach
    back into decisions already made. This is why the master is bitemporal rather than a table.

Ratios are exact integer pairs. A 5:4 bonus is ``4 -> 9`` shares and the price factor is 4/9,
which no float represents; in a system whose prices are integer paise, an adjustment drifting
in the fifteenth decimal produces off-by-one-paise reconciliation failures that look like data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final

from pydantic import field_validator, model_validator

from pips.core.config import PipsConfig
from pips.data.pit.instruments import validate_isin
from pips.data.pit.store import PitRecord, PitStore, from_payload

__all__ = [
    "ActionKind",
    "CorporateAction",
    "CorporateActionMaster",
    "JumpVerdict",
    "UnadjustableActionError",
]

TABLE: Final = "corporate_actions"

# How far an observed ex-date move may sit from the theoretical factor and still count as
# explained. A split predicts an exact factor; the market also moves that day, so the band has
# to admit a normal day's move without admitting corruption. +/-10% accepts a 1:2 split opening
# anywhere in [0.45, 0.55] — generous for an Indian mid-cap, and it still rejects the 0.1 that
# a decimal-shift corruption produces.
#
# UNCALIBRATED PLACEHOLDER, declared as one. The honest version measures the distribution of
# ex-date opening moves against theoretical factors once the master carries real actions, and
# sets the band from that. Until then this is a judgement, not a measurement.
JUMP_TOLERANCE: Final = Decimal("0.10")


class UnadjustableActionError(ValueError):
    """An action whose price factor this project has not decided how to compute."""


class ActionKind(StrEnum):
    """What the action does to the shares or the cash."""

    SPLIT = "SPLIT"
    BONUS = "BONUS"
    DIVIDEND = "DIVIDEND"
    RIGHTS = "RIGHTS"
    OTHER = "OTHER"

    @property
    def is_share_ratio(self) -> bool:
        """Whether the action has an exact price factor from a share ratio alone."""
        return self in (ActionKind.SPLIT, ActionKind.BONUS)


class CorporateAction(PipsConfig):
    """One announced action. ``ex_date`` is a business attribute, not the record's valid time.

    The record is valid from the moment it is announced — that is what ``known_from`` carries.
    Conflating the two would make an announced-but-not-yet-effective action unreadable, and
    "we knew a split was coming" is exactly the kind of thing a decision needs to know.
    """

    action_id: str
    isin: str
    kind: ActionKind
    ex_date: date
    shares_before: int = 1
    shares_after: int = 1
    dividend_paise: int = 0

    @field_validator("isin")
    @classmethod
    def _isin(cls, value: str) -> str:
        return validate_isin(value)

    @model_validator(mode="after")
    def _ratio_is_sane(self) -> CorporateAction:
        if self.kind.is_share_ratio and (self.shares_before < 1 or self.shares_after < 1):
            raise ValueError(
                f"{self.action_id}: shares_before={self.shares_before} "
                f"shares_after={self.shares_after} — a ratio action must turn a positive "
                "number of shares into a positive number of shares. A zero or negative side "
                "yields an infinite or negative price factor, which would silently corrupt "
                "every bar before the ex-date."
            )
        return self

    def price_factor(self) -> Decimal:
        """Exact multiplicative factor applied to bars strictly before the ex-date."""
        if not self.kind.is_share_ratio:
            raise UnadjustableActionError(
                f"{self.action_id}: a {self.kind} has no share ratio, so it has no exact "
                "price factor. Returning 1 would leave a real discontinuity in the series "
                "with nothing to show for it. Adjusting for it is a PRICE-RETURN vs "
                "TOTAL-RETURN decision this project has not made — make it deliberately, in "
                "an ADR, rather than by default here."
            )
        return Decimal(self.shares_before) / Decimal(self.shares_after)


@dataclass(frozen=True)
class JumpVerdict:
    """Whether a known action accounts for an observed ex-date price jump."""

    explained: bool
    reason: str


class CorporateActionMaster:
    """The corporate-action table, over a :class:`PitStore`."""

    def __init__(self, store: PitStore) -> None:
        self.store = store

    # ------------------------------------------------------------- writing ----------

    def announce(self, action: CorporateAction, known_from: date) -> None:
        """Record an action as known from a date."""
        self.store.append(
            PitRecord(
                table=TABLE,
                key=action.action_id,
                valid_from=known_from,
                known_from=known_from,
                payload=action.model_dump(mode="json"),
            )
        )

    def revise(self, action_id: str, action: CorporateAction, known_from: date) -> None:
        """Record a revised action as a NEW knowledge version (§3.4, never an overwrite)."""
        self.store.correct(
            TABLE, action_id, known_from=known_from, payload=action.model_dump(mode="json")
        )

    def cancel(self, action_id: str, known_from: date) -> None:
        """Record that the action was cancelled, as of this knowledge date.

        A run made before the cancellation used the action; a run made after does not. Both
        are correct for their own decision times, and a flat table can hold only one of them.
        """
        self.store.close(TABLE, action_id, known_from=known_from)

    # ------------------------------------------------------------- reading ----------

    def as_of(self, on: date) -> list[CorporateAction]:
        """Every action known on that date, whether or not its ex-date has arrived."""
        return [
            from_payload(CorporateAction, r.payload)
            for r in self.store.as_of(TABLE, known_on=on, valid_on=on)
        ]

    def effective_between(self, isin: str, bar_on: date, as_of: date) -> list[CorporateAction]:
        """Actions for ``isin`` that have taken effect between a bar and a decision time.

        The causality rule, in one place so it cannot drift between the adjuster and any
        future caller: strictly after the bar, at or before the decision.
        """
        return [
            action
            for action in self.as_of(as_of)
            if action.isin == isin and bar_on < action.ex_date <= as_of
        ]

    def adjustment_factor(self, isin: str, bar_on: date, as_of: date) -> Decimal:
        """Exact factor to apply to a bar at ``bar_on``, as understood at ``as_of``."""
        factor = Decimal(1)
        for action in self.effective_between(isin, bar_on, as_of):
            factor *= action.price_factor()
        return factor

    # ------------------------------------------------------------- the QC hook ------

    def explains_jump(
        self,
        isin: str,
        on: date,
        previous_close_paise: int,
        open_paise: int,
        as_of: date | None = None,
    ) -> JumpVerdict:
        """Whether a known action accounts for an ex-date jump (§6 M5's QC check).

        ``as_of`` defaults to the day itself, and that default is the point: QC runs on the
        day, and an action recorded a week later did not explain anything at the time.
        Letting it do so retroactively would quietly un-quarantine historical records.
        """
        when = on if as_of is None else as_of
        if previous_close_paise <= 0:
            return JumpVerdict(False, "previous close is not positive — no ratio to explain")

        observed = Decimal(open_paise) / Decimal(previous_close_paise)
        actions = [a for a in self.as_of(when) if a.isin == isin and a.ex_date == on]
        if not actions:
            return JumpVerdict(
                False,
                f"no known action for {isin} on {on.isoformat()} as of {when.isoformat()}; "
                f"observed ratio {observed:.4f} is unexplained",
            )

        expected = Decimal(1)
        for action in actions:
            if not action.kind.is_share_ratio:
                # An action we cannot price cannot explain a jump either. Saying so beats
                # accepting the jump because *an* action exists that day.
                return JumpVerdict(
                    False,
                    f"{action.kind} on {on.isoformat()} has no exact price factor, so it "
                    f"cannot account for the observed ratio {observed:.4f}",
                )
            expected *= action.price_factor()

        kinds = "+".join(a.kind for a in actions)
        if abs(observed - expected) <= JUMP_TOLERANCE * expected:
            return JumpVerdict(
                True,
                f"{kinds} on {on.isoformat()} predicts {expected:.4f}; "
                f"observed {observed:.4f} — within {JUMP_TOLERANCE:.0%}",
            )
        # An action on the day is not a licence to accept ANY jump. If the price moved far
        # from what the action predicts, something else happened too, and waving it through
        # is how a real corruption gets cleared by the very table meant to catch it.
        return JumpVerdict(
            False,
            f"{kinds} on {on.isoformat()} predicts {expected:.4f} but observed "
            f"{observed:.4f} — outside {JUMP_TOLERANCE:.0%}; the action does not account "
            "for this jump",
        )
