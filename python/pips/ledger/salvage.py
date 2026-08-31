"""The harvest map — `ledger/salvage.yaml` (§1.2, constitution rule 13).

Before any connector, adapter, session/token flow, instrument master, downloader or calendar
is written, this file is consulted. A donor row points at the exact blob it was found in;
a `NONE_FOUND` row pre-authorises from-scratch work, but only by recording what was searched.
"I didn't look" is not valid provenance (§1.1 rule 4), so the schema refuses to express it.

Donors are frequently NOT at HEAD — the best commit is the last one where the component
demonstrably worked, which in these repos is often a commit before a refactor deleted it.
"""

from __future__ import annotations

import re
import subprocess
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "NEEDS_COVERAGE",
    "Decision",
    "SalvageRow",
    "SearchRecord",
    "check_salvage",
    "load_salvage",
    "main",
    "verify_donors",
]

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

# The infrastructure needs §1.2 requires an answer for. Each must be named by some row's
# `covers_needs`, whether that row is a donor or a NONE_FOUND.
# ADR-0010 removed "M23 broker-zerodha adapter": Flattrade is the sole venue. SAL-0024
# stays in salvage.yaml as history — a NONE_FOUND that was true when it was written —
# it simply no longer answers a live need.
NEEDS_COVERAGE: tuple[str, ...] = (
    "M4 session-token flow",
    "M4 historical fetcher",
    "M4 rate-limit budgeter",
    "M4 backfill orchestrator",
    "M4 websocket capture",
    "M6 instrument master",
    "M6 exchange calendar",
    "M6 corporate actions",
    "M21 breeze reader",
    "M23 broker-flattrade adapter",
    "ops alerting",
)


class Decision(StrEnum):
    """What we will do with a candidate component."""

    VENDOR = "VENDOR"  # copy in under vendor/past/ with PROVENANCE.md
    PORT = "PORT"  # rewrite to §3 contracts, keeping the edge-case knowledge
    WRAP = "WRAP"  # keep as-is behind an adapter seam
    SKIP = "SKIP"  # looked at, not worth taking
    NONE_FOUND = "NONE_FOUND"  # searched, nothing qualifies -> from-scratch pre-authorised


class SearchRecord(BaseModel):
    """Evidence that a `NONE_FOUND` actually searched (§1.2)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repos: list[str] = Field(min_length=1)
    refs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    method: str = ""

    @model_validator(mode="after")
    def _must_name_refs_and_keywords(self) -> SearchRecord:
        if not self.refs:
            raise ValueError("searched.refs must name the refs swept — a NONE_FOUND needs evidence")
        if not self.keywords:
            raise ValueError("searched.keywords must name the terms hunted")
        return self


class SalvageRow(BaseModel):
    """One candidate component from the M1 harvest audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    component: str
    decision: Decision
    covers_needs: list[str] = Field(default_factory=list)
    repo: str | None = None
    path: str | None = None
    commit: str | None = None
    ref: str | None = None
    found_at_head: bool | None = None
    size_bytes: int | None = None
    searched: SearchRecord | None = None
    notes: str = ""

    @model_validator(mode="after")
    def _donor_rows_resolve_to_a_blob(self) -> SalvageRow:
        if not self.covers_needs:
            raise ValueError(f"{self.id}: covers_needs must name at least one need")
        if self.decision is Decision.NONE_FOUND:
            if self.searched is None:
                raise ValueError(f"{self.id}: NONE_FOUND requires a `searched:` record")
            return self
        if not self.path:
            raise ValueError(f"{self.id}: decision {self.decision} requires a path")
        if not self.commit:
            raise ValueError(f"{self.id}: decision {self.decision} requires a source commit SHA")
        if not _SHA_RE.match(self.commit):
            raise ValueError(f"{self.id}: commit {self.commit!r} is not a 7-40 char hex SHA")
        return self


def load_salvage(path: Path) -> list[SalvageRow]:
    """Load and validate every row in ``salvage.yaml``."""
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [SalvageRow.model_validate(r) for r in raw]


def check_salvage(root: Path) -> list[str]:
    """Every need in :data:`NEEDS_COVERAGE` names a donor or a NONE_FOUND. Empty == green."""
    rows = load_salvage(root / "docs" / "ledger" / "salvage.yaml")
    if not rows:
        return []  # M1 has not run yet; ledger-check reports that separately
    covered = {need for row in rows for need in row.covers_needs}
    return [
        f"no salvage row covers {need!r} — name a donor or record a NONE_FOUND (§1.2)"
        for need in NEEDS_COVERAGE
        if need not in covered
    ]


def verify_donors(rows: list[SalvageRow], past_dir: Path) -> list[str]:
    """Resolve every donor row's ``<commit>:<path>`` against ``past_dir``. Empty == green.

    Read-only: ``git cat-file`` never mutates the donor repo, which stays untouchable
    (§1.1 rule 1). This cannot run in CI -- ``../past`` is not in the container or on the
    VM -- so it is `make salvage-verify`, run where the donors actually live.
    """
    failures: list[str] = []
    for row in rows:
        if row.decision is Decision.NONE_FOUND or not (row.repo and row.path and row.commit):
            continue
        repo = past_dir / row.repo
        if not (repo / ".git").exists():
            failures.append(f"{row.id}: no git repo at {repo}")
            continue
        probe = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-s", f"{row.commit}:{row.path}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            failures.append(f"{row.id}: {row.repo} {row.commit}:{row.path} does not resolve")
            continue
        size = int(probe.stdout.strip())
        if row.size_bytes is not None and size != row.size_bytes:
            failures.append(
                f"{row.id}: {row.path} is {size}b at {row.commit}, row claims {row.size_bytes}b"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: ``pips salvage verify [past_dir]``."""
    args = list(argv if argv is not None else sys.argv[1:])
    past = Path(args[0]) if args else Path("../past")
    rows = load_salvage(Path("docs/ledger/salvage.yaml"))
    donors = [r for r in rows if r.decision is not Decision.NONE_FOUND]
    failures = verify_donors(rows, past)
    if failures:
        print(f"salvage-verify FAILED ({len(failures)} problem(s)):")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    none_found = len(rows) - len(donors)
    print(
        f"salvage-verify OK: {len(donors)} donor row(s) resolve to real blobs in {past}; "
        f"{none_found} NONE_FOUND row(s) carry a search record"
    )
    return 0
