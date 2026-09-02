"""Writes that land whole, or not at all.

Both users rewrite a whole state file **once per unit of work** -- the backfill manifest once
per key (234,900 times on the 3y x U300 campaign), the call budget once per call (90,000 times
a day) -- and `Path.write_text` truncates before it writes. A process killed inside any one of
those windows leaves a truncated file, and both readers do the safe thing with one: the
manifest starts empty and re-fetches everything already paid for, the budgeter assumes the
day is spent. Safe, and expensive.

Shared rather than copied. There were two copies of this for one tick and that is already one
too many -- two copies of a rule are two places for it to drift, and only one of them is the
one under test.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["atomic_write_text"]


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` so a reader sees the old bytes or the new ones, never both.

    ``os.replace`` is atomic within a filesystem, so the temp file is created beside the
    target rather than in the system temp directory -- a rename across filesystems is a copy,
    which is exactly the non-atomic write this exists to avoid.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
