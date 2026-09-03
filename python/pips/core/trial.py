"""Trial identity and the result cache  [C-ID-01] (§3.1).

A trial is identified by everything that could change its result. §3.1 names the list and
says identity hashes **all** of it: code commit, data snapshot root, instrument-master /
corporate-action / calendar hashes, pipeline DAG, universe policy, parameters, split
definition, cost model, fill model, capital tier, seed, runtime versions.

The hash is taken over the model's own dump rather than a hand-written tuple, so a field
added to :class:`TrialIdentity` is hashed by construction. The completeness test in
``tests/unit/core/test_trial_identity.py`` iterates the same field list and fails if any one
of them stops changing the id -- because the failure mode is silent: two distinct trials that
hash alike collide, and the second returns the first one's cached result.

Re-running an existing hash returns the cached result (§3.1). The cache is content-addressed
and stores the identity beside the result: a result without a resolvable identity is not
evidence (rule 3).
"""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import Field

from pips.core.atomic import atomic_write_text
from pips.core.config import PipsConfig
from pips.core.ids import ShortId, content_hash, short_id

__all__ = [
    "TrialCache",
    "TrialIdentity",
    "current_runtime_versions",
    "git_commit",
]

_TRACKED_PACKAGES = ("polars", "duckdb", "numpy", "pydantic")


def git_commit(root: Path | None = None) -> str:
    """The exact commit under test. Falls back to a marker rather than lying.

    An unknown commit must not silently look like a known one, so the fallback is a value
    that can never collide with a real SHA and is obvious in a registry row.
    """
    probe = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root or Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.stdout.strip() if probe.returncode == 0 else "UNKNOWN-NOT-A-GIT-CHECKOUT"


def current_runtime_versions() -> dict[str, str]:
    """Interpreter and pinned library versions.

    These belong in the identity precisely because they differ between machines: a result
    produced under a different numeric stack is a different trial, not the same one.
    """
    versions = {"python": ".".join(str(p) for p in sys.version_info[:3])}
    for package in _TRACKED_PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:  # pragma: no cover - env-specific
            versions[package] = "absent"
    return versions


class TrialIdentity(PipsConfig):
    """Everything that could change a trial's result, in one content-addressed object.

    Every field is hashed. Adding a field here adds it to the identity automatically; the
    completeness test enforces that nothing is added *without* being hashed.
    """

    code_commit: str
    data_snapshot_root: str
    instrument_master_hash: str
    corporate_action_hash: str
    calendar_hash: str
    pipeline_dag_hash: str
    universe_policy_hash: str
    split_definition_hash: str
    cost_model_hash: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    fill_tier: str
    capital_tier: str
    seed: int
    runtime_versions: dict[str, str] = Field(default_factory=dict)

    def trial_id(self) -> str:
        """Full SHA-256 over the canonical encoding of every field.

        Hashes the **python-mode** dump, not the JSON one, and that is not a detail.
        Pydantic's JSON serialiser turns a non-finite float into ``null`` by default, so a
        parameter of ``inf`` and a parameter of ``None`` would hash identically -- two
        different trials silently sharing one id and one cached result. Python mode keeps
        the float, and :func:`~pips.core.ids.canonicalize` refuses it, which is what
        [C-NUM-01] requires: NaN and infinities do not cross a schema boundary. The same
        strictness rejects any parameter type the canonical encoding has no definition for,
        rather than stringifying it into a collision.
        """
        return content_hash(self.model_dump())

    def short_id(self) -> ShortId:
        """First 16 hex of the trial id -- the human-facing form."""
        return short_id(self.trial_id())


class TrialCache:
    """Content-addressed store of trial results, keyed by trial id.

    Deliberately not the experiment registry [C-REG-01]: the registry is the append-only
    record of *every viewed trial* (rule 4), while this only avoids recomputing an identical
    one. A cache hit is not a reason to skip registering the trial.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, trial_id: str) -> Path:
        """Where a trial's entry lives. Sharded by prefix to keep directories small."""
        return self.root / trial_id[:2] / f"{trial_id}.json"

    def entry_for(self, trial_id: str) -> dict[str, Any] | None:
        """The full entry -- identity and result -- or ``None`` on a miss."""
        path = self.path_for(trial_id)
        if not path.exists():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A kill mid-write leaves a truncated entry, and a bare `json.loads` would raise
            # here on every later lookup -- permanently, until someone deleted the file by
            # hand. The crash would surface as the search failing on a trial it has run before,
            # long after the crash that caused it.
            #
            # A MISS IS THE RIGHT ANSWER BECAUSE THIS IS A CACHE. `Manifest.load` states the
            # same rule for the same shape: "Starting from empty re-fetches, which costs
            # budget; assuming everything is done would leave silent holes. Cost is the better
            # failure." Silently missing would be WRONG for the registry `[C-REG-01]`, where an
            # uncounted trial flatters deflation -- which is why this class says in its own
            # docstring that it is deliberately not that.
            return None
        if not isinstance(loaded, dict):
            # `json.loads` succeeds on `null`, `3` and `[]`. Returning one would move the crash
            # one frame out, into whoever indexes the result -- the same `TypeError` case
            # `CaptureWriter._last_seq_on_disk` catches beside its `ValueError`.
            return None
        entry: dict[str, Any] = loaded
        return entry

    def get(self, trial_id: str) -> dict[str, Any] | None:
        """The cached result for ``trial_id``, or ``None`` on a miss."""
        entry = self.entry_for(trial_id)
        return None if entry is None else dict(entry["result"])

    def put(self, identity: TrialIdentity, result: dict[str, Any]) -> str:
        """Store a result against its identity. Returns the trial id."""
        trial_id = identity.trial_id()
        path = self.path_for(trial_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "trial_id": trial_id,
            "identity": identity.model_dump(mode="json"),
            "result": result,
        }
        # Canonical, sorted JSON: the same result must produce the same bytes on every
        # machine, or `make determinism` would fail on the cache rather than on the maths.
        # Atomic, so a crash cannot leave a truncated entry at all -- reading one gracefully
        # is the second line of defence, not the first. `core/atomic.py` exists for this and
        # says why: "two copies of a rule are two places for it to drift".
        atomic_write_text(
            path,
            json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        )
        return trial_id

    def run_or_load(
        self, identity: TrialIdentity, compute: Callable[[], dict[str, Any]]
    ) -> tuple[dict[str, Any], bool]:
        """Return ``(result, was_cached)``, computing only on a miss (§3.1)."""
        trial_id = identity.trial_id()
        cached = self.get(trial_id)
        if cached is not None:
            return cached, True
        result = compute()
        self.put(identity, result)
        return result, False
