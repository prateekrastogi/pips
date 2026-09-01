"""The lockbox one-shot run: opening the holdout exactly once  (§3.6, M20, `[C-LBOX-01]`).

Two halves already existed. M11 built the ledger — every unlock recorded, append-only, a second
attempt voids the cycle (:meth:`pips.search.registry.Registry.unlock_holdout`). M18 built the
refusal — the data layer will not hand over the bytes from below the release stage
(:class:`pips.data.lockbox.SealedLockbox`). Neither of them *runs* the holdout, and the gap
between them is where the one thing a lockbox exists to prevent can still happen.

**The unlock is recorded BEFORE the evaluation, not after it.** Recording a successful unlock is
the natural order and it is the wrong one. An evaluation that crashes has still fetched the
sealed window; a caller who retries then gets a fresh "first" unlock, and crash-and-retry reads
the holdout as many times as it likes with one row to show for it. This runner cannot know how
far the evaluation got before it died, and the only assumption that cannot silently permit a
second look is that it got all the way. So a crashed run consumes the cycle, and the retry is
told the cycle is VOID.

**A refusal costs nothing.** The mirror of the above: if a stray S3 call burned the cycle's one
unlock, any process could void every certification in flight by asking politely and being told
no. A refused caller never saw the data and owes nothing — the seal records the attempt, which
is the right ledger for it.

**The window is the seal's, never the caller's.** A run that evaluates the training window and
reports it as the holdout is what makes the whole gate theatre, so this takes no dates at all.
The cycle id comes from the seal for the same reason: a caller supplying both could unlock cycle
A's ledger while reading cycle B's holdout.

**An empty result is not a pass.** A run that measured nothing must not be reportable as a run
that measured nothing bad — the same absence-as-data failure the dossier refuses placeholders
for (`[C-DOSS-01]`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from datetime import date

    from pips.data.lockbox import SealedLockbox
    from pips.search.registry import Registry

__all__ = ["EmptyLockboxRunError", "LockboxRun", "run_lockbox_once"]


class EmptyLockboxRunError(ValueError):
    """The holdout was opened and nothing was measured. Not a pass; not reportable."""


@dataclass(frozen=True)
class LockboxRun:
    """One irreversible look at the sealed window. Frozen: evidence that can be edited after
    the fact is not evidence."""

    cycle_id: str
    config_hash: str
    stage: str
    start: date
    end: date
    metrics: Mapping[str, float]

    def summary(self) -> dict[str, Any]:
        """JSON-safe, so the run can be sealed into a dossier section and hashed there.

        `dates` become ISO strings because `dossier_hash` is plain JSON and would raise on a
        `date` — a summary nobody tried to seal would carry that break to the first real
        certification.
        """
        return {
            "cycle_id": self.cycle_id,
            "config_hash": self.config_hash,
            "stage": self.stage,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "metrics": dict(self.metrics),
        }


def run_lockbox_once(
    *,
    registry: Registry,
    lockbox: SealedLockbox,
    config_hash: str,
    stage: str,
    evaluate: Callable[[date, date], Mapping[str, float] | None],
) -> LockboxRun:
    """Open the holdout once, evaluate it, and record that it was opened.

    Raises :class:`pips.data.lockbox.LockboxSealedError` from below the release stage (without
    consuming the unlock), ``RuntimeError`` if the cycle was already opened (without re-reading
    it), and :class:`EmptyLockboxRunError` if the evaluation measured nothing (having consumed
    the unlock, because it looked).
    """
    if not config_hash.strip():
        raise ValueError(
            "config_hash is empty: the unlock row would record that the cycle was opened and "
            "not what it was opened for, which is a ledger entry nobody can act on."
        )

    # ORDER MATTERS THREE TIMES BELOW, and each order is the opposite of the obvious one.
    #
    # 1. The seal is asked first, so a refused caller never reaches the ledger. The seal records
    #    the attempt itself, which is where a refusal belongs.
    lockbox.check(stage, lockbox.start, lockbox.end)

    # 2. The unlock is recorded before the read, so a crash cannot unsee it — and it raises on a
    #    second call before `evaluate` runs, so the void is declared without a second look.
    registry.unlock_holdout(lockbox.cycle_id, config_hash)

    # 3. Only now.
    metrics = evaluate(lockbox.start, lockbox.end)

    if not metrics:
        raise EmptyLockboxRunError(
            f"the holdout for cycle {lockbox.cycle_id!r} was opened and the evaluation returned "
            "nothing. The unlock stands — it looked — but a run that measured nothing is not a "
            "run that measured nothing bad, and there is no result to report."
        )

    return LockboxRun(
        cycle_id=lockbox.cycle_id,
        config_hash=config_hash,
        stage=stage,
        start=lockbox.start,
        end=lockbox.end,
        # Copied: the caller's dict is not evidence, and a later edit must not rewrite the run.
        metrics=dict(metrics),
    )
