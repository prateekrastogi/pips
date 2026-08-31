"""Joining the M6 masters to QC's verdict seam  [C-DATA-01] (§6 M5/M6).

`check_unexplained_ratio_jump` takes a verdict; :class:`CorporateActionMaster` produces one.
The join between them is the reason the seam is a callable rather than a master object:
**bronze carries a SYMBOL and the action master is keyed on ISIN.** Resolving one to the other
is the instrument master's job, and it must be done AS-OF — a symbol the exchange has since
lent to another company would otherwise resolve to whoever holds it today, and the actions of
one security would be used to explain the prices of another.

Three outcomes, deliberately kept apart:

resolved, action accounts for the move
    explained; no finding.
resolved, nothing accounts for it
    unexplained; quarantined.
not resolved
    unexplained; quarantined, and the reason says the symbol is unknown.

The third matters. "I could not identify this security" is a different fact from "this
security had no corporate action", and reporting the first as the second is a lookup that
could not answer being recorded as an answer — which is the failure mode this project keeps
finding in its own work.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

from pips.data.pit.corporate_actions import CorporateActionMaster, JumpVerdict
from pips.data.pit.instruments import AmbiguousSymbolError, InstrumentMaster
from pips.data.pit.store import PitStore

__all__ = ["JumpExplainer", "jump_explainer"]

JumpExplainer = Callable[[str, date, int, int], JumpVerdict | None]
"""``(symbol, day, previous_close_paise, open_paise) -> verdict``."""


def jump_explainer(pit_root: Path) -> JumpExplainer | None:
    """Build the QC verdict callable over a PIT store, or ``None`` if there is no store.

    ``None`` rather than an explainer that always answers "unexplained": QC treats a missing
    verdict as fail-closed, and the distinction between *nothing to consult* and *consulted
    and found nothing* belongs in the caller's warning, not buried in a reason string.
    """
    if not Path(pit_root).exists():
        return None

    store = PitStore(pit_root)
    instruments = InstrumentMaster(store)
    actions = CorporateActionMaster(store)

    def explain(symbol: str, day: date, previous_close_paise: int, open_paise: int) -> JumpVerdict:
        # BOTH IDENTIFIER SPACES. pips' bronze is keyed by the DATA VENDOR's code (RELIND)
        # while the master's `symbol` is the exchange's (RELIANCE), and a broker fill will
        # carry the exchange one. Asking only for the symbol meant that with 5,851 real
        # instruments loaded, the seam still reported "RELIND is not in the instrument
        # master" — and QC could not show it, because a run with no ratio jumps never calls
        # the explainer at all.
        try:
            by_vendor = instruments.resolve_vendor_code(symbol, on=day)
            by_symbol = instruments.resolve_symbol(symbol, on=day)
        except AmbiguousSymbolError as exc:
            # Two live claims on one identifier. Refusing to guess here is the same refusal
            # the master makes, carried through to QC instead of swallowed into a verdict.
            return JumpVerdict(False, f"symbol {symbol!r} is ambiguous on {day}: {exc}")

        if by_vendor is not None and by_symbol is not None and by_vendor != by_symbol:
            # One string, two securities, by different routes. Taking the first is how one
            # company's actions get used to explain another's prices.
            return JumpVerdict(
                False,
                f"{symbol!r} is ambiguous on {day.isoformat()}: it is the vendor code of "
                f"{by_vendor.isin} and the exchange symbol of {by_symbol.isin}",
            )
        instrument = by_vendor or by_symbol
        if instrument is None:
            return JumpVerdict(
                False,
                f"symbol {symbol!r} is not in the instrument master as of {day.isoformat()}, "
                "so no corporate action could be looked up — this is an unidentified "
                "security, NOT a security with no actions",
            )
        return actions.explains_jump(
            instrument.isin,
            on=day,
            previous_close_paise=previous_close_paise,
            open_paise=open_paise,
        )

    return explain
