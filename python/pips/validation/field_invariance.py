"""Field-invariance perturbation check  (§6 M16, A05's falsifier).

A05 pre-registered *"Reject if the result depends on the first untradeable print"*, and the
plugin is already built so that it does not: ``session_gaps`` measures to the first bar's CLOSE
rather than the opening auction price, precisely because that falsifier exists.

But **"the code is written that way" is not a check.** This runs the perturbation — change the
field, recompute, see whether anything moved. A construction that is correct today and quietly
edited tomorrow fails here; a comment claiming the same thing does not.

Two things make it a test rather than a ceremony:

**The perturbation must actually change the input.** An invariance check whose perturbation had
no effect passes for every implementation ever written. That is not hypothetical here:
``_load_panel`` does not carry ``open_paise`` at all, so a check that shrugged at a missing
column would report A05 invariant to a field the panel never contained — a green meaning
nothing, on the exact falsifier it was built to evaluate. A missing field is ``ran=False``, and
``ran=False`` is not invariant.

**A perturbation selecting no rows is refused**, because that is the degenerate version of the
same hole, and it would otherwise report a clean pass over an untouched panel.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

import polars as pl

__all__ = ["InvarianceVerdict", "field_invariance"]

Compute = Callable[[pl.DataFrame], dict[str, Decimal]]
"""``frame -> {instrument: score}``. Injected, so the check is pure and reusable."""

# Enough to move any real computation, and unmistakable in a diff. Not a fraction of the
# value: a multiplicative nudge can vanish into rounding on small numbers, and an invariance
# check that perturbs below the noise floor of its own arithmetic proves nothing.
_PERTURBATION_PAISE = 9_999


@dataclass(frozen=True)
class InvarianceVerdict:
    """Whether the computation moved when the field did."""

    field: str
    ran: bool
    rows_perturbed: int
    changed: tuple[str, ...]
    note: str = ""

    @property
    def invariant(self) -> bool:
        """Ran, and nothing moved. A check that could not run is not invariant."""
        return self.ran and not self.changed


def field_invariance(
    compute: Compute,
    frame: pl.DataFrame,
    field: str,
    rows: tuple[int, ...],
    by: int = _PERTURBATION_PAISE,
) -> InvarianceVerdict:
    """Perturb ``field`` on ``rows`` by ``by`` and report which outputs moved.

    ``by`` is caller-supplied because different fields need different magnitudes — and because
    it makes the "did the input actually move" guard reachable. With a fixed perturbation that
    guard could never fire, and a mutation removing it killed nothing: dead defence that reads
    as live defence.
    """
    if not rows:
        raise ValueError(
            "field_invariance perturbed no rows. An invariance check whose perturbation had "
            "no effect passes for every implementation ever written."
        )
    outside = [i for i in rows if not 0 <= i < frame.height]
    if outside:
        raise ValueError(f"row index {outside} is outside the panel of {frame.height} rows")

    if field not in frame.columns:
        # NOT a pass. The panel does not contain the field, so nothing was tested — and
        # `_load_panel` genuinely omits `open_paise`, which is how this arises for real.
        return InvarianceVerdict(
            field=field,
            ran=False,
            rows_perturbed=0,
            changed=(),
            note=(
                f"panel has no column {field!r}, so the perturbation could not be applied. "
                "Nothing was tested; this is not invariance."
            ),
        )

    baseline = compute(frame)
    original = frame[field].to_list()
    perturbed_values = [v + by if i in set(rows) else v for i, v in enumerate(original)]
    perturbed_frame = frame.with_columns(pl.Series(field, perturbed_values))

    # VERIFY THE INPUT MOVED before drawing any conclusion from the outputs matching. "We
    # asked for a change" and "the frame differs" are not the same statement.
    actually_changed = sum(1 for a, b in zip(original, perturbed_values, strict=True) if a != b)
    if actually_changed == 0:
        raise ValueError(
            f"perturbing {field!r} on rows {rows} changed no value in the panel, so any "
            "conclusion about invariance would be about a panel nobody perturbed."
        )

    after = compute(perturbed_frame)
    changed = tuple(sorted(key for key in baseline if baseline.get(key) != after.get(key))) + tuple(
        sorted(set(after) - set(baseline))
    )
    return InvarianceVerdict(
        field=field, ran=True, rows_perturbed=actually_changed, changed=changed
    )
