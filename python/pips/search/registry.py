"""Append-only experiment registry  [C-REG-01] (§3.6, constitution rule 4).

*Every viewed trial counts.* Completed, failed, abandoned, hand-tuned, alternative-seed and
notebook-glanced variants all land here, and **deletion does not un-count a trial**. A
registry that can be quietly edited is a leaderboard, and a leaderboard is what this project
is explicitly not building.

§3.6 says "application code has no UPDATE/DELETE". This goes further and enforces it with
SQLite **triggers**, because "the application does not do that" is a property of today's
application: a trigger also refuses a ``sqlite3`` shell, a stray migration, and a future
contributor who is only trying to fix one row.

Daily returns are preserved per trial for exactly one reason: ``M_erank`` and SPA need the
cross-trial correlation matrix, and it cannot be reconstructed after the fact.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Final

import numpy as np
import polars as pl
from pydantic import Field, field_validator, model_validator

from pips.core.config import PipsConfig

__all__ = ["STAGE_RANKS", "VALID_STATUSES", "Registry", "RunRecord"]

# S1=1, S2V=2, S2E=3, S3=4, S4=5, S5=6, S6=7 (§3.6). The rank orders the funnel, so a rank
# that contradicts its stage would silently reorder it.
STAGE_RANKS: Final[dict[str, int]] = {
    "S1": 1,
    "S2V": 2,
    "S2E": 3,
    "S3": 4,
    "S4": 5,
    "S5": 6,
    "S6": 7,
}
VALID_STATUSES: Final[frozenset[str]] = frozenset({"completed", "failed", "abandoned", "viewed"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id INTEGER PRIMARY KEY, config_hash TEXT NOT NULL, stage TEXT NOT NULL,
  stage_rank INTEGER NOT NULL,
  family TEXT, universe_id TEXT, session_mask TEXT, capital_tier TEXT, broker TEXT,
  data_snapshot TEXT NOT NULL, cost_model TEXT NOT NULL, fill_tier TEXT NOT NULL,
  seed INTEGER NOT NULL, git_sha TEXT NOT NULL, metrics TEXT NOT NULL, n_trades INTEGER,
  daily_returns_ref TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS holdout_unlocks (
  cycle_id TEXT, config_hash TEXT, unlocked_at TEXT DEFAULT (datetime('now'))
);

-- Append-only, enforced here rather than by convention. RAISE(ABORT) surfaces as
-- sqlite3.IntegrityError to any caller, including one that is not this application.
CREATE TRIGGER IF NOT EXISTS runs_no_update BEFORE UPDATE ON runs
BEGIN SELECT RAISE(ABORT, 'runs is append-only (rule 4): a trial cannot be edited'); END;
CREATE TRIGGER IF NOT EXISTS runs_no_delete BEFORE DELETE ON runs
BEGIN SELECT RAISE(ABORT, 'runs is append-only (rule 4): deletion does not un-count a trial'); END;
CREATE TRIGGER IF NOT EXISTS unlocks_no_update BEFORE UPDATE ON holdout_unlocks
BEGIN SELECT RAISE(ABORT, 'holdout_unlocks is append-only: an unlock attempt is evidence'); END;
CREATE TRIGGER IF NOT EXISTS unlocks_no_delete BEFORE DELETE ON holdout_unlocks
BEGIN SELECT RAISE(ABORT, 'holdout_unlocks is append-only: an unlock attempt is evidence'); END;
"""


class RunRecord(PipsConfig):
    """One trial. Every field that could change the result is already in the config hash."""

    config_hash: str
    stage: str
    stage_rank: int
    data_snapshot: str
    cost_model: str
    fill_tier: str
    seed: int
    git_sha: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    status: str
    family: str | None = None
    universe_id: str | None = None
    session_mask: str | None = None
    capital_tier: str | None = None
    broker: str | None = None
    n_trades: int | None = None
    daily_returns_ref: str | None = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value not in VALID_STATUSES:
            raise ValueError(
                f"status {value!r} is not one of {sorted(VALID_STATUSES)} — an unrecognised "
                "status would be counted but not classified, which defeats the ledger"
            )
        return value

    @model_validator(mode="after")
    def _rank_matches_stage(self) -> RunRecord:
        expected = STAGE_RANKS.get(self.stage)
        if expected is None:
            raise ValueError(f"unknown stage {self.stage!r}; expected one of {sorted(STAGE_RANKS)}")
        if self.stage_rank != expected:
            raise ValueError(
                f"stage_rank {self.stage_rank} contradicts stage {self.stage!r} "
                f"(expected {expected}) — the rank orders the funnel"
            )
        return self


class Registry:
    """The append-only trial store."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(_SCHEMA)
        self.connection.commit()

    # -- writing ----------------------------------------------------------------------
    def record(self, run: RunRecord) -> int:
        """Append a trial. There is no update path, by construction."""
        payload = run.model_dump()
        payload["metrics"] = json.dumps(payload["metrics"], sort_keys=True)
        columns = ", ".join(payload)
        placeholders = ", ".join(f":{k}" for k in payload)
        cursor = self.connection.execute(
            f"INSERT INTO runs ({columns}) VALUES ({placeholders})", payload
        )
        self.connection.commit()
        return int(cursor.lastrowid or 0)

    def write_daily_returns(self, path: Path, returns: np.ndarray) -> Path:
        """Persist a trial's daily returns. Preserved for ``M_erank`` and SPA (§3.6)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame({"daily_return": np.asarray(returns, dtype=float)}).write_parquet(path)
        return path

    # -- reading ----------------------------------------------------------------------
    def get(self, run_id: int) -> RunRecord | None:
        row = self.connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        # Explicit column list rather than iterating the Row: `for k in row` yields VALUES,
        # not keys, so the terse form ruff prefers would silently produce nonsense here.
        payload = {name: row[name] for name in RunRecord.model_fields}
        payload["metrics"] = json.loads(payload["metrics"])
        return RunRecord.model_validate(payload)

    def all_runs(self) -> list[sqlite3.Row]:
        """Every trial, in insertion order. No filtering: that is the point (rule 4)."""
        return list(self.connection.execute("SELECT * FROM runs ORDER BY run_id"))

    def daily_returns_matrix(self) -> np.ndarray | None:
        """Columns of preserved daily returns, truncated to their common length.

        ``None`` when nothing was preserved -- the honest answer, since ``M_erank`` cannot be
        computed without them and defaulting it to ``M`` would understate the correction.
        """
        refs = [r["daily_returns_ref"] for r in self.all_runs() if r["daily_returns_ref"]]
        if not refs:
            return None
        series = [pl.read_parquet(ref)["daily_return"].to_numpy() for ref in refs]
        length = min(len(s) for s in series)
        return np.column_stack([s[:length] for s in series])

    # -- the holdout lockbox ----------------------------------------------------------
    def holdout_unlock_count(self, cycle_id: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS n FROM holdout_unlocks WHERE cycle_id = ?", (cycle_id,)
        ).fetchone()
        return int(row["n"])

    def unlock_holdout(self, cycle_id: str, config_hash: str) -> None:
        """Unlock a cycle's holdout. Once. A second attempt voids the cycle (§3.6).

        The attempt is recorded **before** it is refused. Refusing and forgetting would hide
        that someone tried, and a lockbox exists precisely to make that visible.
        """
        already = self.holdout_unlock_count(cycle_id)
        self.connection.execute(
            "INSERT INTO holdout_unlocks (cycle_id, config_hash) VALUES (?, ?)",
            (cycle_id, config_hash),
        )
        self.connection.commit()
        if already:
            raise RuntimeError(
                f"holdout for cycle {cycle_id!r} was already unlocked — this cycle is now "
                "VOID (§3.6: one unlock per cycle; twice = void). The attempt has been "
                "recorded. Start a new cycle; do not report the second look."
            )
