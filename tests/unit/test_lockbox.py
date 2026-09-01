"""Sealed-lockbox enforcement in the data layer  (§6 M18, §3.6).

M11 built the ledger half: every unlock attempt is recorded, append-only, and a second attempt
voids the cycle. That records what happened. It does not stop it.

This is the other half — **the data layer refuses to hand over the bytes**. A holdout that is
merely a convention is a holdout that gets read: not maliciously, but by a loop that widens its
date range by a month, or a notebook that asks for "everything". The only holdout that survives
contact with a research process is one that cannot be fetched.

The design decision that matters is what refusal LOOKS like:

**It raises. It does not filter.** Silently returning the portion outside the holdout is the
worst option available, because the caller then computes a perfectly valid-looking result over
a window it did not choose and has no way to notice. A shorter series is not an error message.
That is the same failure as a rate-limited HTTP 200 recorded as "no data", arriving at the one
place the project has agreed not to look.

**Every attempt is recorded, refused ones included.** Refusing and forgetting hides that
someone tried, and a lockbox exists precisely to make that visible (§3.6).

**An unknown stage is refused, not assumed.** A stage nobody recognises is not evidence of
authority to read sealed data.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.data.lockbox import LockboxSealedError, SealedLockbox

D = date
HOLDOUT_START = D(2026, 7, 1)
HOLDOUT_END = D(2027, 1, 1)


def lockbox(release_stage: str = "S6") -> SealedLockbox:
    return SealedLockbox(
        start=HOLDOUT_START, end=HOLDOUT_END, release_stage=release_stage, cycle_id="C1"
    )


# ------------------------------------------------------------ the refusal --------------


def test_a_request_overlapping_the_holdout_is_refused_below_the_release_stage() -> None:
    with pytest.raises(LockboxSealedError, match="sealed"):
        lockbox().check(stage="S3", start=D(2026, 6, 1), end=D(2026, 8, 1))


def test_a_request_entirely_before_the_holdout_passes() -> None:
    # The control. Without it, "refuses" could be what the lockbox always does.
    lockbox().check(stage="S3", start=D(2026, 1, 1), end=HOLDOUT_START)


def test_a_request_entirely_after_the_holdout_passes() -> None:
    lockbox().check(stage="S3", start=HOLDOUT_END, end=D(2027, 6, 1))


def test_it_raises_rather_than_returning_the_part_outside_the_holdout() -> None:
    """The design decision, stated as a test.

    Silently trimming the request to the visible window is the worst available option: the
    caller computes a valid-looking result over a window it did not choose, with a shorter
    series as its only clue — and a shorter series is not an error message.

    So `check` returns None or raises. There is deliberately no "give me what you can" path,
    because a caller that wanted one would use it.
    """
    box = lockbox()
    with pytest.raises(LockboxSealedError) as excinfo:
        box.check(stage="S3", start=D(2026, 6, 1), end=D(2026, 8, 1))
    assert "2026-07-01" in str(excinfo.value), "the message must name the sealed window"
    assert not hasattr(box, "check_partial"), "no partial path may exist for a caller to find"


# ------------------------------------------------------------ the stage ----------------


def test_the_release_stage_opens_the_box() -> None:
    lockbox().check(stage="S6", start=D(2026, 6, 1), end=D(2026, 8, 1))


def test_every_stage_below_release_is_refused() -> None:
    for stage in ("S1", "S2V", "S2E", "S3", "S4", "S5"):
        with pytest.raises(LockboxSealedError):
            lockbox().check(stage=stage, start=D(2026, 6, 1), end=D(2026, 8, 1))


def test_the_ordering_comes_from_the_registrys_stage_ranks() -> None:
    """Not a second copy of the funnel's order.

    Two hand-maintained orderings drift, and this one decides whether sealed data is readable.
    A lockbox that thinks S5 is above S6 opens early and nothing else notices.
    """
    from pips.search.registry import STAGE_RANKS

    box = lockbox(release_stage="S4")
    for stage, rank in STAGE_RANKS.items():
        if rank >= STAGE_RANKS["S4"]:
            box.check(stage=stage, start=D(2026, 6, 1), end=D(2026, 8, 1))
        else:
            with pytest.raises(LockboxSealedError):
                box.check(stage=stage, start=D(2026, 6, 1), end=D(2026, 8, 1))


def test_an_unrecognised_stage_is_refused_not_assumed() -> None:
    # A stage nobody recognises is not evidence of authority to read sealed data.
    with pytest.raises(LockboxSealedError, match="unknown stage"):
        lockbox().check(stage="S99", start=D(2026, 6, 1), end=D(2026, 8, 1))


def test_an_unrecognised_release_stage_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="release stage"):
        SealedLockbox(start=HOLDOUT_START, end=HOLDOUT_END, release_stage="LATER", cycle_id="C1")


# ------------------------------------------------------------ the record ---------------


def test_a_refused_attempt_is_recorded() -> None:
    """Refusing and forgetting hides that someone tried (§3.6)."""
    seen: list[tuple[str, str, bool]] = []
    box = SealedLockbox(
        start=HOLDOUT_START,
        end=HOLDOUT_END,
        release_stage="S6",
        cycle_id="C1",
        on_attempt=lambda cycle, stage, allowed: seen.append((cycle, stage, allowed)),
    )
    with pytest.raises(LockboxSealedError):
        box.check(stage="S3", start=D(2026, 6, 1), end=D(2026, 8, 1))
    assert seen == [("C1", "S3", False)]


def test_an_allowed_attempt_is_recorded_too() -> None:
    # Only recording refusals would make the record a list of failures rather than of accesses,
    # and the question "who read the holdout" is the one that matters after release.
    seen: list[tuple[str, str, bool]] = []
    box = SealedLockbox(
        start=HOLDOUT_START,
        end=HOLDOUT_END,
        release_stage="S6",
        cycle_id="C1",
        on_attempt=lambda cycle, stage, allowed: seen.append((cycle, stage, allowed)),
    )
    box.check(stage="S6", start=D(2026, 6, 1), end=D(2026, 8, 1))
    assert seen == [("C1", "S6", True)]


def test_a_request_that_never_touches_the_holdout_is_not_an_attempt() -> None:
    # Recording every read of ordinary data would bury the ones that matter.
    seen: list[tuple[str, str, bool]] = []
    box = SealedLockbox(
        start=HOLDOUT_START,
        end=HOLDOUT_END,
        release_stage="S6",
        cycle_id="C1",
        on_attempt=lambda cycle, stage, allowed: seen.append((cycle, stage, allowed)),
    )
    box.check(stage="S1", start=D(2026, 1, 1), end=D(2026, 3, 1))
    assert seen == []


# ------------------------------------------------------------ boundaries ---------------


def test_the_holdout_window_is_half_open() -> None:
    """[start, end): the end date itself is outside.

    Stated because an off-by-one here either seals a day that should be readable or, worse,
    exposes the first day of the holdout.
    """
    box = lockbox()
    box.check(stage="S1", start=D(2026, 1, 1), end=HOLDOUT_START)
    box.check(stage="S1", start=HOLDOUT_END, end=D(2027, 2, 1))
    with pytest.raises(LockboxSealedError):
        box.check(stage="S1", start=HOLDOUT_START, end=D(2026, 7, 2))


def test_an_inverted_window_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="starts"):
        SealedLockbox(start=HOLDOUT_END, end=HOLDOUT_START, release_stage="S6", cycle_id="C1")


def test_an_inverted_request_is_refused() -> None:
    with pytest.raises(ValueError, match="starts"):
        lockbox().check(stage="S1", start=D(2026, 8, 1), end=D(2026, 6, 1))


# ------------------------------------------------- wired into the read path -------------
# A check nothing consults is a dead check — the lesson from `check_unexplained_ratio_jump`,
# which was written at M5, unit-tested, and never called by the runner for a whole milestone.


def test_the_panel_loader_refuses_a_read_that_touches_the_holdout(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The lockbox is consulted where research data is actually read.

    The fixtures span 2026-06-01 to 06-03. A lockbox sealing June from stage S1 must stop the
    panel from loading at all — not return a shorter one.
    """
    from pips.search.s1 import load_panel

    box = SealedLockbox(start=D(2026, 6, 1), end=D(2026, 7, 1), release_stage="S6", cycle_id="C1")
    with pytest.raises(LockboxSealedError):
        load_panel(Path("fixtures"), lockbox=box, stage="S1")


def test_the_panel_loader_allows_the_read_at_the_release_stage() -> None:
    from pips.search.s1 import load_panel

    box = SealedLockbox(start=D(2026, 6, 1), end=D(2026, 7, 1), release_stage="S6", cycle_id="C1")
    assert load_panel(Path("fixtures"), lockbox=box, stage="S6").height > 0


def test_the_panel_loader_is_unguarded_when_no_lockbox_is_given() -> None:
    # No lockbox means no holdout has been declared, which is different from a holdout that
    # permits everything — and the default must not silently become the latter.
    from pips.search.s1 import load_panel

    assert load_panel(Path("fixtures")).height > 0


def test_a_lockbox_without_a_stage_is_refused_by_the_loader() -> None:
    """A read of unknown provenance cannot be authorised against a holdout.

    Defaulting the stage would authorise it — and whichever default were chosen would be
    wrong: a permissive one opens the box, a restrictive one blocks every ordinary read until
    someone "fixes" it by passing the permissive value everywhere. A mutation removing this
    guard survived until now.
    """
    from pips.search.s1 import load_panel

    box = SealedLockbox(start=D(2026, 6, 1), end=D(2026, 7, 1), release_stage="S6", cycle_id="C1")
    with pytest.raises(ValueError, match="without a stage"):
        load_panel(Path("fixtures"), lockbox=box)
