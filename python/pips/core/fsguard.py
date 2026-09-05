"""Refuse an output root that cannot be written BEFORE doing the work that would fill it.

arb-vm, 2026-09-05: `pips daily promote` built 4.6 million rows for 26 minutes and then died on
`mkdir('/srv/pips/daily')` -- the container's uid may write inside the data root's existing
directories but not create a new one at its top. A run that cannot end in a write must not
begin: the check is a real write (create if absent, probe file, unlink), not a permission-bit
guess, because bind mounts, ACLs and setgid directories all lie to `os.access`.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

__all__ = ["writable_directory"]


def writable_directory(path: Path) -> str | None:
    """``None`` if ``path`` is (or can be made) a directory we can write into, else why not.

    A directory this call created is removed again, so a run that then finds nothing to do
    leaves no empty artifact directory behind to be mistaken for an output.
    """
    created = not path.exists()
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".pips-write-probe-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        return f"cannot write {path}: {error.strerror or error}. Fix the plant, then re-run."
    if created:
        with contextlib.suppress(OSError):  # somebody else already used it; that is fine
            path.rmdir()
    return None
