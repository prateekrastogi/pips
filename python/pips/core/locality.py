"""Rule 14, in one place: market data never enters the working tree.

ALL market data and runtime state live on arb-vm volumes; the laptop holds code and fixtures.
Easy to get wrong from a laptop, and the consequence -- market data in git -- is one of the
few mistakes here that cannot be fully undone.

**This guard fails silently when it fails**, which is why it is worth being careful about. It
allows a path by concluding the path is outside the repository, so anything that makes the
repository un-findable reads as permission. The two copies this replaces each located the
repository as ``Path(__file__).resolve().parents[4]`` -- correct only while the file stays
exactly four directories deep, and silently permissive the moment it does not.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["refuse_repo_paths", "repo_root"]


def repo_root() -> Path | None:
    """The working tree this code runs from, found by its marker rather than by depth.

    ``None`` when there is no working tree -- an installed package has no repository to
    protect, and refusing every path in that case would block the deployed service from
    writing anywhere at all.
    """
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def refuse_repo_paths(root: Path, *, what: str) -> None:
    """Raise if ``root`` is inside the working tree.

    ``what`` names the data being written, so the message says which write was stopped rather
    than leaving the reader to work it out from a traceback.
    """
    repo = repo_root()
    if repo is None:
        return
    try:
        root.resolve().relative_to(repo)
    except ValueError:
        return
    raise ValueError(
        f"refusing to write {what} inside the repository ({root}). ALL market data lives on "
        "arb-vm under /srv/pips (rule 14); the laptop holds code and fixtures only."
    )
