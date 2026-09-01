"""The lockbox one-shot run: opening the holdout exactly once  (§3.6, M20, `[C-LBOX-01]`).

Two halves already exist. M11 built the ledger — every unlock recorded, append-only, a second
attempt voids the cycle. M18 built the refusal — the data layer will not hand over the bytes
from below the release stage. Neither of them *runs* the holdout, and the gap between them is
where the one thing the lockbox exists to prevent can still happen.

**The unlock is recorded before the evaluation, not after it.** Recording a successful unlock is
the natural order and it is the wrong one: an evaluation that crashes has still fetched the
holdout, and a caller who retries then gets a fresh "first" unlock. Crash-and-retry reads the
sealed window as many times as it likes with one row to show for it. The runner cannot know how
far the evaluation got before it died, and the only assumption that cannot silently permit a
second look is that it got all the way.

**A refusal must not consume the unlock.** The mirror of the above: if a stray S3 call burned the
cycle's one unlock, any process could void every certification by asking politely and being told
no. Refused callers never saw the data, so they owe nothing.

**The window is the lockbox's, never the caller's.** A run that evaluates the training window and
reports it as the holdout is what makes the whole gate theatre, so the runner takes no dates at
all and reads them off the seal.

**An empty result is not a pass.** A run that measured nothing must not be reportable as a run
that measured nothing bad.
"""

from __future__ import annotations

import inspect
from datetime import date
from typing import TYPE_CHECKING, Any

import pytest

from pips.certification.dossier import REQUIRED_FIELDS, build_dossier
from pips.certification.lockbox_run import (
    EmptyLockboxRunError,
    LockboxRun,
    run_lockbox_once,
)
from pips.data.lockbox import LockboxSealedError, SealedLockbox
from pips.search.registry import Registry

if TYPE_CHECKING:
    from pathlib import Path

START, END = date(2026, 7, 1), date(2026, 8, 1)
CONFIG = "c" * 64


_DEFAULT = object()
"""A sentinel distinct from every value under test. `None` cannot serve: it is one of the empty
results these tests need to pass in, and using it for both makes that case silently untested."""


class Evaluation:
    """Records what it was asked for, and how often."""

    def __init__(self, result: Any = _DEFAULT, raises: Exception | None = None) -> None:
        self.result = {"net_sharpe": 1.2} if result is _DEFAULT else result
        self.raises = raises
        self.calls: list[tuple[date, date]] = []

    def __call__(self, start: date, end: date) -> Any:
        self.calls.append((start, end))
        if self.raises is not None:
            raise self.raises
        return self.result


def seal() -> SealedLockbox:
    attempts: list[tuple[str, str, bool]] = []
    box = SealedLockbox(
        start=START,
        end=END,
        release_stage="S6",
        cycle_id="cycle-1",
        on_attempt=lambda c, s, a: attempts.append((c, s, a)),
    )
    box.attempts = attempts  # type: ignore[attr-defined]
    return box


def registry(tmp_path: Path) -> Registry:
    return Registry(tmp_path / "registry.db")


# ------------------------------------------------------------------- the happy path -----


def test_a_release_stage_run_returns_the_metrics(tmp_path: Path) -> None:
    reg, box, ev = registry(tmp_path), seal(), Evaluation()

    run = run_lockbox_once(registry=reg, lockbox=box, config_hash=CONFIG, stage="S6", evaluate=ev)

    assert run.metrics == {"net_sharpe": 1.2}
    assert reg.holdout_unlock_count("cycle-1") == 1


def test_the_run_names_what_it_was_run_for(tmp_path: Path) -> None:
    """A result that does not name its configuration can be reported for a different one."""
    run = run_lockbox_once(
        registry=registry(tmp_path),
        lockbox=seal(),
        config_hash=CONFIG,
        stage="S6",
        evaluate=Evaluation(),
    )
    assert run.config_hash == CONFIG
    assert run.cycle_id == "cycle-1"
    assert run.stage == "S6"
    assert (run.start, run.end) == (START, END)


# --------------------------------------------------------- the window is not the caller's -----


def test_the_evaluation_receives_the_holdout_window(tmp_path: Path) -> None:
    ev = Evaluation()
    run_lockbox_once(
        registry=registry(tmp_path), lockbox=seal(), config_hash=CONFIG, stage="S6", evaluate=ev
    )
    assert ev.calls == [(START, END)]


def test_the_runner_accepts_no_dates_of_its_own() -> None:
    """Structural: a run that evaluates the training window and calls it the holdout is what
    makes the gate theatre, and the cheapest way to make that impossible is to have nowhere to
    pass the wrong dates."""
    taken = set(inspect.signature(run_lockbox_once).parameters)
    assert not (taken & {"start", "end", "window", "dates"}), taken


def test_the_cycle_comes_from_the_seal_not_the_caller() -> None:
    """Otherwise a caller can unlock cycle A's ledger while reading cycle B's holdout."""
    assert "cycle_id" not in inspect.signature(run_lockbox_once).parameters


# -------------------------------------------------------------- record before evaluate -----


def test_a_crashed_evaluation_still_consumed_the_unlock(tmp_path: Path) -> None:
    """The runner cannot know how far the evaluation got before it died.

    Recording only successful unlocks is the natural order and the wrong one: a crash-and-retry
    loop then reads the sealed window as many times as it likes with one row to show for it.
    """
    reg, box = registry(tmp_path), seal()
    ev = Evaluation(raises=ZeroDivisionError("mid-evaluation"))

    with pytest.raises(ZeroDivisionError):
        run_lockbox_once(registry=reg, lockbox=box, config_hash=CONFIG, stage="S6", evaluate=ev)

    assert reg.holdout_unlock_count("cycle-1") == 1, "the holdout was fetched; the crash is later"


def test_retrying_after_a_crash_voids_the_cycle(tmp_path: Path) -> None:
    reg, box = registry(tmp_path), seal()
    with pytest.raises(ZeroDivisionError):
        run_lockbox_once(
            registry=reg,
            lockbox=box,
            config_hash=CONFIG,
            stage="S6",
            evaluate=Evaluation(raises=ZeroDivisionError("mid-evaluation")),
        )

    with pytest.raises(RuntimeError, match="VOID"):
        run_lockbox_once(
            registry=reg, lockbox=box, config_hash=CONFIG, stage="S6", evaluate=Evaluation()
        )


def test_a_second_run_voids_the_cycle_without_re_reading_it(tmp_path: Path) -> None:
    """The raise has to come before the evaluation, or the second look happens anyway."""
    reg, box, ev = registry(tmp_path), seal(), Evaluation()
    run_lockbox_once(registry=reg, lockbox=box, config_hash=CONFIG, stage="S6", evaluate=ev)

    with pytest.raises(RuntimeError, match="VOID"):
        run_lockbox_once(registry=reg, lockbox=box, config_hash=CONFIG, stage="S6", evaluate=ev)

    assert len(ev.calls) == 1, "the sealed window was read a second time before the refusal"


# ------------------------------------------------------------------- refusals cost nothing -----


def test_a_run_from_below_the_release_stage_is_refused(tmp_path: Path) -> None:
    ev = Evaluation()
    with pytest.raises(LockboxSealedError):
        run_lockbox_once(
            registry=registry(tmp_path),
            lockbox=seal(),
            config_hash=CONFIG,
            stage="S3",
            evaluate=ev,
        )
    assert ev.calls == []


def test_a_refused_attempt_does_not_consume_the_unlock(tmp_path: Path) -> None:
    """Otherwise any process could void every certification by asking and being told no."""
    reg, box = registry(tmp_path), seal()
    with pytest.raises(LockboxSealedError):
        run_lockbox_once(
            registry=reg, lockbox=box, config_hash=CONFIG, stage="S3", evaluate=Evaluation()
        )

    assert reg.holdout_unlock_count("cycle-1") == 0
    run = run_lockbox_once(
        registry=reg, lockbox=box, config_hash=CONFIG, stage="S6", evaluate=Evaluation()
    )
    assert run.metrics


def test_a_refused_attempt_is_still_recorded_by_the_seal(tmp_path: Path) -> None:
    box = seal()
    with pytest.raises(LockboxSealedError):
        run_lockbox_once(
            registry=registry(tmp_path),
            lockbox=box,
            config_hash=CONFIG,
            stage="S3",
            evaluate=Evaluation(),
        )
    assert box.attempts == [("cycle-1", "S3", False)]  # type: ignore[attr-defined]


def test_an_unknown_stage_is_refused(tmp_path: Path) -> None:
    with pytest.raises(LockboxSealedError):
        run_lockbox_once(
            registry=registry(tmp_path),
            lockbox=seal(),
            config_hash=CONFIG,
            stage="S9",
            evaluate=Evaluation(),
        )


# ------------------------------------------------------------------- nothing is not a pass -----


@pytest.mark.parametrize("nothing", [{}, None])
def test_an_empty_result_is_not_a_pass(tmp_path: Path, nothing: Any) -> None:
    with pytest.raises(EmptyLockboxRunError):
        run_lockbox_once(
            registry=registry(tmp_path),
            lockbox=seal(),
            config_hash=CONFIG,
            stage="S6",
            evaluate=Evaluation(result=nothing),
        )


def test_an_empty_result_still_consumed_the_unlock(tmp_path: Path) -> None:
    """It measured nothing, but it looked."""
    reg = registry(tmp_path)
    with pytest.raises(EmptyLockboxRunError):
        run_lockbox_once(
            registry=reg,
            lockbox=seal(),
            config_hash=CONFIG,
            stage="S6",
            evaluate=Evaluation(result={}),
        )
    assert reg.holdout_unlock_count("cycle-1") == 1


@pytest.mark.parametrize("anonymous", ["", "   ", "\t", "\n"])
def test_an_anonymous_config_hash_is_refused(tmp_path: Path, anonymous: str) -> None:
    """The ledger row would say the cycle was opened, and not for what.

    Whitespace is included because it is the version that looks filled in — the same
    absence-wearing-the-costume-of-data the dossier refuses placeholders for.
    """
    reg, ev = registry(tmp_path), Evaluation()
    with pytest.raises(ValueError, match="config_hash"):
        run_lockbox_once(
            registry=reg, lockbox=seal(), config_hash=anonymous, stage="S6", evaluate=ev
        )

    assert ev.calls == []
    assert reg.holdout_unlock_count("cycle-1") == 0


# ------------------------------------------------------------------------ the evidence -----


def test_a_later_edit_cannot_rewrite_the_result(tmp_path: Path) -> None:
    """The metrics are evidence; the caller's dict is not."""
    mutable = {"net_sharpe": 1.2}
    run = run_lockbox_once(
        registry=registry(tmp_path),
        lockbox=seal(),
        config_hash=CONFIG,
        stage="S6",
        evaluate=Evaluation(result=mutable),
    )
    mutable["net_sharpe"] = 99.0
    assert run.metrics == {"net_sharpe": 1.2}


def test_the_summary_can_be_sealed_into_a_dossier(tmp_path: Path) -> None:
    """The run is only evidence if it can reach the artifact that carries evidence.

    `dossier_hash` is plain JSON, so a `date` or a dataclass inside a section raises rather than
    hashing — and a summary nobody ever tried to seal would carry that break to the first real
    certification.
    """
    run = run_lockbox_once(
        registry=registry(tmp_path),
        lockbox=seal(),
        config_hash=CONFIG,
        stage="S6",
        evaluate=Evaluation(),
    )
    sections: dict[str, dict[str, Any]] = {
        name: {field: f"{name}.{field}" for field in fields}
        for name, fields in REQUIRED_FIELDS.items()
    }
    sections["stability"]["lockbox_result"] = run.summary()

    assert build_dossier(sections).dossier_hash()


def test_the_run_is_frozen() -> None:
    """Evidence that can be edited after the fact is not evidence."""
    assert LockboxRun.__dataclass_params__.frozen  # type: ignore[attr-defined]
