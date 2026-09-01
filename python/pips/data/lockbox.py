"""Sealed-lockbox enforcement in the data layer  (§6 M18, §3.6).

M11 built the ledger half: every unlock attempt recorded, append-only, a second attempt voiding
the cycle. That records what happened. It does not stop it.

This is the other half — **the data layer refuses to hand over the bytes**. A holdout that is
merely a convention is a holdout that gets read: not maliciously, but by a loop that widens its
date range by a month, or a notebook that asks for "everything". The only holdout that survives
contact with a research process is one that cannot be fetched.

What refusal LOOKS like is the design decision:

**It raises. It does not filter.** Silently returning the portion outside the holdout is the
worst option available: the caller computes a perfectly valid-looking result over a window it
did not choose, with a shorter series as its only clue — and a shorter series is not an error
message. That is the same failure as a rate-limited HTTP 200 recorded as "no data", arriving at
the one place this project has agreed not to look. There is deliberately no "give me what you
can" path, because a caller who wanted one would use it.

**Every attempt that touches the holdout is recorded, refused ones included.** Refusing and
forgetting hides that someone tried, and a lockbox exists precisely to make that visible.
Requests that never touch it are not recorded — logging every ordinary read would bury the ones
that matter.

**An unknown stage is refused.** A stage nobody recognises is not evidence of authority to read
sealed data.

The stage ordering comes from :data:`pips.search.registry.STAGE_RANKS` rather than a second
copy. Two hand-maintained orderings drift, and a lockbox that thinks S5 outranks S6 opens early
with nothing else noticing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from pips.search.registry import STAGE_RANKS

__all__ = ["LockboxSealedError", "SealedLockbox"]

AttemptHook = Callable[[str, str, bool], None]
"""``(cycle_id, stage, allowed) -> None``. A callback, so the data layer does not depend on
the registry -- the ledger is the caller's business, and this module's job is the refusal."""


class LockboxSealedError(PermissionError):
    """A request touched sealed holdout dates from below the release stage."""


@dataclass
class SealedLockbox:
    """A half-open ``[start, end)`` holdout window that opens only at the release stage."""

    start: date
    end: date
    release_stage: str
    cycle_id: str
    on_attempt: AttemptHook | None = field(default=None)

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(
                f"holdout starts {self.start} and ends {self.end}; an empty or inverted "
                "window seals nothing while looking like it seals something"
            )
        if self.release_stage not in STAGE_RANKS:
            raise ValueError(
                f"unknown release stage {self.release_stage!r}; expected one of "
                f"{sorted(STAGE_RANKS)}. A release stage nobody recognises can never be "
                "reached, or worse, might be treated as reached."
            )

    def _overlaps(self, start: date, end: date) -> bool:
        return start < self.end and self.start < end

    def check(self, stage: str, start: date, end: date) -> None:
        """Permit the read, or raise. There is no third outcome, by design."""
        if end <= start:
            raise ValueError(f"request starts {start} and ends {end}")
        if not self._overlaps(start, end):
            return

        allowed = stage in STAGE_RANKS and STAGE_RANKS[stage] >= STAGE_RANKS[self.release_stage]
        if self.on_attempt is not None:
            # RECORDED BEFORE THE REFUSAL, so a raise cannot skip it. M11 makes the same
            # choice for the same reason: the attempt is the evidence.
            self.on_attempt(self.cycle_id, stage, allowed)
        if allowed:
            return

        if stage not in STAGE_RANKS:
            raise LockboxSealedError(
                f"unknown stage {stage!r} requested sealed dates "
                f"[{self.start}, {self.end}); a stage nobody recognises is not evidence of "
                "authority to read them"
            )
        raise LockboxSealedError(
            f"dates [{self.start}, {self.end}) are sealed until stage "
            f"{self.release_stage} and this request came from {stage}. The request is "
            "refused whole: returning the part outside the holdout would let a result be "
            "computed over a window nobody chose, and a shorter series is not an error."
        )
