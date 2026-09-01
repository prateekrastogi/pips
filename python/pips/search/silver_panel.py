"""Reading silver as a search panel  (§6 M6/M12).

Real bars live in `/srv/pips/silver` — two names over three trading days, promoted from bronze
by :func:`pips.data.silver.promote_bronze` — and the search has only ever read generated
fixtures. This is the loader that lets it read them.

**A second reader is a second door into the holdout.** :func:`pips.search.s1.load_panel` consults
the sealed lockbox because the read is the only place it can bite; a loader that skipped the
check would reopen exactly the hole the lockbox exists to close, and would look like a
convenience while doing it. The check is SHARED — `_check_lockbox` — not reimplemented, because
two copies of one rule is two places for it to drift and only one of them would be the one under
test.

**The columns the search reads are named.** A silver file missing ``close_paise`` is not a panel
with one fewer column; it is a panel every alpha reads zero prices from, and the failure would
surface as a KeyError three modules deep inside somebody's compute.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from pips.search.s1 import _check_lockbox

if TYPE_CHECKING:
    from pathlib import Path

    from pips.data.lockbox import SealedLockbox

__all__ = ["REQUIRED_COLUMNS", "load_silver_panel"]

REQUIRED_COLUMNS: frozenset[str] = frozenset(
    {
        "close_ts_ns",
        "symbol",
        "open_paise",
        "high_paise",
        "low_paise",
        "close_paise",
        "volume",
    }
)
"""What every alpha needs. `isin` and `received_at_ns` ride along and are not required here."""


def load_silver_panel(
    parquet: Path, lockbox: SealedLockbox | None = None, stage: str | None = None
) -> pl.DataFrame:
    """Load promoted bars as a panel the search can read."""
    if not parquet.exists():
        raise FileNotFoundError(
            f"no silver bars at {parquet}. Promote bronze first: "
            "`pips.data.silver.promote_bronze(bronze_root, silver_root, master, known_on=...)`."
        )

    panel = pl.read_parquet(parquet)
    missing = sorted(REQUIRED_COLUMNS - set(panel.columns))
    if missing:
        raise ValueError(
            f"silver at {parquet} is missing {missing}. Refusing rather than loading a partial "
            "panel: a missing price column is not one fewer column, it is a panel every alpha "
            "reads zero prices from, and the failure would surface as a KeyError inside a "
            "compute rather than here."
        )
    if panel.height == 0:
        raise ValueError(
            f"silver at {parquet} holds no bars. An empty panel is not a quiet market — it is a "
            "promotion that wrote nothing, and every series built on it would be empty too."
        )

    _check_lockbox(panel["close_ts_ns"].to_list(), lockbox, stage)
    return panel.sort(["close_ts_ns", "symbol"])
