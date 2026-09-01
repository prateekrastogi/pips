"""Field-invariance perturbation check  (§6 M16, A05's falsifier).

A05 pre-registered *"Reject if the result depends on the first untradeable print"*, and the
plugin is already built so that it does not: `session_gaps` measures to the first bar's CLOSE
rather than the opening auction price, precisely because that falsifier exists.

But "the code is written that way" is not a check. **This runs the perturbation**: change the
untradeable print, recompute, and see whether anything moved. A construction that is correct
today and quietly edited tomorrow fails here; a comment claiming the same thing does not.

The two things that make this a test rather than a ceremony:

**The perturbation must actually change the input.** An invariance check whose perturbation
had no effect passes for every implementation ever written. That is not hypothetical here —
`_load_panel` does not carry `open_paise` at all, so a check that shrugged at a missing column
would report A05 invariant to a field the panel never contained.

**There must be a control that FAILS.** A checker that always reports invariance is
indistinguishable from a correct alpha. So the suite includes a deliberately dependent
computation, and it must be caught.
"""

from __future__ import annotations

from decimal import Decimal

import polars as pl
import pytest

from pips.validation.field_invariance import field_invariance

NS = 1_000_000_000
MIN = 60 * NS
START = 1_780_285_560_000_000_000


def panel(with_open: bool = True) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol in ("AAA", "BBB"):
        for i in range(20):
            row: dict[str, object] = {
                "close_ts_ns": START + i * MIN,
                "symbol": symbol,
                "close_paise": 100_000 + i * 10,
                "volume": 1_000,
            }
            if with_open:
                row["open_paise"] = 100_000 + i * 10 - 5
            rows.append(row)
    return pl.DataFrame(rows).sort(["close_ts_ns", "symbol"])


def ignores_open(frame: pl.DataFrame) -> dict[str, Decimal]:
    """A computation that never touches the perturbed field — the correct shape."""
    return {
        s: Decimal(int(frame.filter(pl.col("symbol") == s)["close_paise"].sum()))
        for s in sorted(set(frame["symbol"].to_list()))
    }


def depends_on_open(frame: pl.DataFrame) -> dict[str, Decimal]:
    """A computation that reads the untradeable print — the failure being hunted."""
    return {
        s: Decimal(int(frame.filter(pl.col("symbol") == s)["open_paise"].sum()))
        for s in sorted(set(frame["symbol"].to_list()))
    }


# ------------------------------------------------------------ the check ----------------


def test_a_computation_that_ignores_the_field_is_invariant() -> None:
    verdict = field_invariance(ignores_open, panel(), field="open_paise", rows=(0,))
    assert verdict.ran
    assert verdict.invariant
    assert verdict.changed == ()


def test_a_computation_that_reads_the_field_is_caught() -> None:
    """The control. Without it, "invariant" could be what this function always says."""
    verdict = field_invariance(depends_on_open, panel(), field="open_paise", rows=(0,))
    assert verdict.ran
    assert not verdict.invariant
    # ONLY AAA. The frame is sorted by (timestamp, symbol), so row 0 is AAA's first bar and
    # BBB is untouched — the check localises the dependence rather than flagging everything.
    # My first assertion demanded both, which would have passed for an implementation that
    # reported every instrument on any change.
    assert verdict.changed == ("AAA",)


def test_the_verdict_names_which_outputs_moved() -> None:
    # Which instrument moved is what turns a failure into a diagnosis.
    both = field_invariance(depends_on_open, panel(), field="open_paise", rows=(0, 1))
    assert both.changed == ("AAA", "BBB"), "perturbing both symbols' first bars moves both"


# ------------------------------------------------------------ vacuity ------------------


def test_a_missing_field_cannot_be_perturbed_and_does_not_pass() -> None:
    """The case that made this worth building.

    `_load_panel` does not carry `open_paise`. A check that shrugged at the missing column
    would report A05 invariant to a field the panel never contained — a green meaning nothing,
    on the exact falsifier it was built to evaluate.
    """
    verdict = field_invariance(ignores_open, panel(with_open=False), field="open_paise", rows=(0,))
    assert verdict.ran is False
    assert verdict.invariant is False, "could not run is not invariant"
    assert "open_paise" in verdict.note


def test_a_perturbation_that_changes_nothing_is_refused() -> None:
    """An invariance check whose perturbation had no effect passes for every implementation.

    Selecting no rows is the degenerate version, and it must fail loudly rather than report a
    clean pass over an untouched panel.
    """
    with pytest.raises(ValueError, match="perturbed no rows"):
        field_invariance(ignores_open, panel(), field="open_paise", rows=())


def test_a_row_index_outside_the_panel_is_refused() -> None:
    with pytest.raises(ValueError, match="outside"):
        field_invariance(ignores_open, panel(), field="open_paise", rows=(999,))


def test_the_perturbation_is_verified_to_have_changed_the_input() -> None:
    # Not merely "we asked for a change" — the check confirms the frame actually differs
    # before drawing any conclusion from the outputs matching.
    verdict = field_invariance(ignores_open, panel(), field="open_paise", rows=(0, 1))
    assert verdict.rows_perturbed == 2


def test_the_check_is_registered_and_resolves() -> None:
    from pips.validation.falsifier_binding import CHECK_REGISTRY, resolve_check

    assert "field-invariance" in CHECK_REGISTRY
    resolve_check("field-invariance")


def test_a_zero_magnitude_perturbation_is_refused() -> None:
    """The guard that had nothing to guard.

    With a fixed perturbation magnitude, "did the input actually move" could never fire, and a
    mutation removing it killed nothing — dead defence that reads as live defence. Making the
    magnitude caller-supplied gives it a real case: a perturbation of zero selects valid rows,
    changes nothing, and would otherwise report a clean invariance over an untouched panel.
    """
    with pytest.raises(ValueError, match="changed no value"):
        field_invariance(ignores_open, panel(), field="open_paise", rows=(0, 1), by=0)
