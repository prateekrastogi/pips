"""Bitemporal PIT store and Merkle snapshot manifests  [C-DATA-01] [C-DATA-02] (§3.4, §6 M6).

Two clocks. **Valid time** is when a fact was true of the world; **knowledge time** is when we
knew it. A backtest that reads today's masters is reading the future — it knows which names
survived, which tickers were reassigned, and which prices were later corrected. §7's rejection
list opens with exactly that failure ("present-day constituents projected backward"), and the
only structural defence is to make the *only* read shape an as-of read.

Three properties carry the weight:

**The log is literally append-only.** ``correct`` and ``close`` append new versions; nothing is
ever mutated or deleted. A version's ``known_to`` is therefore not stored — it is implied by
the next version of the same key, and computed at read time. Storing it would require editing
the previous row, which is the one thing an append-only log must not do.

**A past as-of read never moves.** §6 M6's Verify is byte-identity, not logical equivalence:
serialize a read as of some past date today and again after a year of snapshots, and the bytes
match. That is what lets a result be pinned to a snapshot root and re-derived later.

**Reading the past reproduces our errors.** If a value was wrong on the day, the as-of read
returns the wrong value, because that is what the strategy actually saw. Silently returning
the corrected value would make every historical run unreproducible in the most flattering
direction available.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from pydantic import Field

from pips.core.config import PipsConfig
from pips.core.ids import canonical_bytes

__all__ = [
    "MerkleTree",
    "PitOp",
    "PitRecord",
    "PitStore",
    "SurvivorshipAudit",
    "from_payload",
]

_LEAF: Final = b"\x00"
_NODE: Final = b"\x01"
_EMPTY_ROOT_DOMAIN: Final = b"pips.merkle.empty.v1"


def from_payload[T: PipsConfig](model: type[T], payload: dict[str, Any]) -> T:
    """Rebuild a config model from a PIT payload.

    Payloads are stored as JSON, so they hold ISO date strings and plain enum values. Every
    PipsConfig is strict, and strict PYTHON-mode validation correctly refuses a ``str`` where
    a ``date`` or an enum is declared — a caller handing over ``"2026-07-01"`` has skipped
    parsing it. Strict JSON-mode validation accepts the ISO form, because JSON has no date
    type to have used instead.

    One helper rather than the same round-trip written at each call site: the masters both
    need it, and a rule implemented twice is a rule that drifts.
    """
    return model.model_validate_json(json.dumps(payload))


class PitOp(StrEnum):
    """What a log entry asserts about its key."""

    UPSERT = "UPSERT"
    """The key exists, with this payload, from this knowledge date."""

    CLOSE = "CLOSE"
    """The key left the master on this knowledge date -- delisted, merged, withdrawn.

    A tombstone, not a deletion. The versions before it stay readable, which is what makes a
    survivorship audit possible at all.
    """


class PitRecord(PipsConfig):
    """One immutable version of one key, in both clocks."""

    table: str
    key: str
    valid_from: date
    known_from: date
    payload: dict[str, Any] = Field(default_factory=dict)
    op: PitOp = PitOp.UPSERT

    def leaf(self) -> str:
        """Canonical bytes of this record, hex-hashed -- its Merkle leaf."""
        return hashlib.sha256(canonical_bytes(self.model_dump(mode="json"))).hexdigest()


@dataclass(frozen=True)
class SurvivorshipAudit:
    """Which keys were readable at the earlier date and are gone by the later one."""

    table: str
    earlier: date
    later: date
    survived: list[str]
    disappeared: list[str]

    @property
    def population(self) -> int:
        return len(self.survived) + len(self.disappeared)

    def describe(self) -> str:
        """One line, phrased so the loss is the subject rather than a footnote."""
        return (
            f"{self.table}: {len(self.survived)} of {self.population} keys readable on "
            f"{self.earlier.isoformat()} were still readable on {self.later.isoformat()}; "
            f"{len(self.disappeared)} disappeared ({', '.join(self.disappeared) or 'none'}). "
            "A study restricted to the survivors is a study of survivors."
        )


class PitStore:
    """An append-only bitemporal log, one JSONL file per table.

    JSONL rather than a database because the guarantee being sold is byte-identity: a file of
    one canonical JSON object per line, appended and never rewritten, makes that guarantee
    inspectable with ``diff``. Order within the file is the tie-break sequence, so the file is
    the authority on ordering and nothing has to be reconstructed.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # Parsed records per table, with the file SIZE they were parsed at. `append` enforces
        # the forward-only rule by asking for the latest version, which read and re-validated
        # the whole file every time — so appending N records cost N full parses of a file
        # growing to N lines. The real instrument master (5,851 rows) turned a one-second
        # parse into a ten-minute ingest. Correct at fixture scale, unusable at production
        # scale, and no test would ever have said so.
        self._cache: dict[str, list[PitRecord]] = {}
        self._cached_size: dict[str, int] = {}
        self.file_parses = 0
        """Full file parses performed. Exposed so the read amplification can be ASSERTED as a
        bound rather than measured as a duration -- a timing test would be flaky and would not
        say what was slow."""

    # ---------------------------------------------------------------- writing --------

    def _path(self, table: str) -> Path:
        return self.root / f"{table}.jsonl"

    def append(self, record: PitRecord) -> None:
        """Append a version. The only write primitive; everything else composes it."""
        latest = self._latest_version(record.table, record.key, known_on=None)
        if latest is not None and record.known_from < latest.known_from:
            # Backdating a knowledge date rewrites what we would have read on a day that has
            # already passed -- and every result produced on that day was computed against the
            # old answer. Late-arriving information is recorded with the date it ARRIVED; the
            # date it became TRUE is valid_from, which may be as far back as you like.
            raise ValueError(
                f"{record.table}/{record.key}: known_from {record.known_from} precedes the "
                f"latest known version {latest.known_from}. Knowledge time only moves forward "
                "— backdate valid_from instead (§3.4)."
            )
        line = json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        path = self._path(record.table)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        # Extend the cache rather than invalidating it: the record we just wrote is the record
        # we already hold, so re-reading the file to learn it would be the original defect in
        # a smaller form.
        if record.table in self._cache:
            self._cache[record.table].append(record)
            self._cached_size[record.table] = path.stat().st_size

    def correct(self, table: str, key: str, known_from: date, payload: dict[str, Any]) -> None:
        """Record a corrected payload as a NEW version (§3.4: never an overwrite)."""
        current = self._require_latest(table, key)
        self.append(
            PitRecord(
                table=table,
                key=key,
                valid_from=current.valid_from,
                known_from=known_from,
                payload=payload,
            )
        )

    def close(self, table: str, key: str, known_from: date) -> None:
        """Record that the key left the master, as of this knowledge date."""
        current = self._require_latest(table, key)
        self.append(
            PitRecord(
                table=table,
                key=key,
                valid_from=current.valid_from,
                known_from=known_from,
                op=PitOp.CLOSE,
            )
        )

    def _require_latest(self, table: str, key: str) -> PitRecord:
        latest = self._latest_version(table, key, known_on=None)
        if latest is None:
            raise KeyError(f"{table}/{key}: no version to amend — append it first")
        return latest

    # ---------------------------------------------------------------- reading --------

    def all_records(self, table: str) -> list[PitRecord]:
        """Every version ever appended, in file order. Nothing is filtered out."""
        path = self._path(table)
        if not path.exists():
            return []

        # The cache is keyed on the file's SIZE, not merely on its presence. Two stores over
        # one directory is exactly how a backfill and a QC pass coexist, and a cache that
        # trusts itself after another process has written reports stale data with total
        # confidence — worse than the slowness it was added to fix. A size change is cheap to
        # check and cannot be missed by an append, which only ever grows the file.
        size = path.stat().st_size
        if self._cached_size.get(table) == size and table in self._cache:
            return self._cache[table]
        self.file_parses += 1
        # ``model_validate_json``, not ``model_validate(json.loads(...))``. PipsConfig is
        # strict, and strict PYTHON-mode validation rejects a str where a date is declared —
        # correctly, since a caller handing us "2026-01-01" has skipped parsing it. JSON has
        # no date type, so strict JSON-mode validation does accept the ISO form. Parsing the
        # line ourselves would throw that distinction away.
        records = [
            PitRecord.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self._cache[table] = records
        self._cached_size[table] = size
        return records

    def _latest_version(
        self, table: str, key: str, known_on: date | None, valid_on: date | None = None
    ) -> PitRecord | None:
        """The version in force for ``key`` on both clocks -- last write wins on a tie.

        BOTH filters are applied BEFORE choosing the latest, and that ordering is the whole
        correctness of the method. An earlier version picked the most recently KNOWN version
        and only then checked whether it was yet valid — so a version recorded today and
        effective next month MASKED the one actually in force, and the key vanished from the
        table entirely. The symptom is a lookup that reports no data for a date that plainly
        has data, which for the capability table would read as "this broker could not trade
        that day".
        """
        winner: PitRecord | None = None
        for record in self.all_records(table):
            if record.key != key:
                continue
            if known_on is not None and record.known_from > known_on:
                continue
            if valid_on is not None and record.valid_from > valid_on:
                continue
            if winner is None or record.known_from >= winner.known_from:
                winner = record
        return winner

    def as_of(self, table: str, known_on: date, valid_on: date | None = None) -> list[PitRecord]:
        """The table as it was readable on ``known_on``, sorted by key.

        ``valid_on`` defaults to ``known_on``: the overwhelmingly common question is "what did
        the world look like on day D, as we understood it on day D", and making the caller
        spell that out twice invites the two dates drifting apart by accident.
        """
        effective_valid = known_on if valid_on is None else valid_on
        keys = sorted({r.key for r in self.all_records(table)})
        out: list[PitRecord] = []
        for key in keys:
            version = self._latest_version(table, key, known_on=known_on, valid_on=effective_valid)
            if version is None or version.op is PitOp.CLOSE:
                continue
            out.append(version)
        return out

    # ------------------------------------------------------- snapshot manifests ------

    def snapshot_root(self, table: str, known_on: date, valid_on: date | None = None) -> str:
        """Merkle root over the as-of snapshot [C-DATA-02].

        Pinning this root next to a result is what makes the result re-derivable: the root
        moves if any byte of the snapshot moves, and does not move otherwise.
        """
        return MerkleTree.root(
            [r.leaf() for r in self.as_of(table, known_on=known_on, valid_on=valid_on)]
        )

    def verify_pinned_root(
        self, table: str, known_on: date, pinned: str, valid_on: date | None = None
    ) -> bool:
        """Whether the store still produces ``pinned`` for that as-of date.

        The failure this catches is not a missing snapshot — that announces itself. It is a
        snapshot that MOVED while keeping its name: someone re-ingests a range, a row lands
        with a ``known_from`` inside an already-pinned window, and every name-based reference
        still resolves. Only a root over bytes notices.

        Ordinary forward progress must not trip it, or it gets switched off. It does not:
        appending at a later knowledge date leaves every earlier snapshot untouched, which is
        the byte-identity guarantee this method is the consumer of.
        """
        return self.snapshot_root(table, known_on=known_on, valid_on=valid_on) == pinned

    def survivorship_audit(self, table: str, earlier: date, later: date) -> SurvivorshipAudit:
        """Which keys readable at ``earlier`` are gone by ``later`` (§6 M6 Verify)."""
        if earlier > later:
            raise ValueError(f"earlier {earlier} is after later {later}")
        then = {r.key for r in self.as_of(table, known_on=earlier)}
        now = {r.key for r in self.as_of(table, known_on=later)}
        return SurvivorshipAudit(
            table=table,
            earlier=earlier,
            later=later,
            survived=sorted(then & now),
            disappeared=sorted(then - now),
        )


class MerkleTree:
    """A binary hash tree over ordered leaves.

    Domain-separated (leaves prefixed ``0x00``, internal nodes ``0x01``) so a leaf's hash can
    never be mistaken for a node's — otherwise a crafted "leaf" that is really an internal
    hash proves membership of something that was never in the tree.

    Honest note on that prefix: a mutation run removing it killed no test, and it should not
    have. Leaves arrive as ``str`` and nodes are raw 32-byte digests, so a leaf preimage
    almost never coincides with a node preimage — the type split already blocks the attack
    the prefix targets. The prefix stays because the type split is an implementation detail
    and the prefix is a guarantee, but what actually pins this scheme is the golden vectors in
    ``tests/unit/test_pit.py``: a snapshot root outlives the code that produced it, so the
    thing to defend is not one prefix but the scheme as a whole never moving unannounced.

    **An odd level promotes its last node unchanged; it does not duplicate it.** Duplication is
    the usual textbook answer and it is broken: it makes ``[a, b, c]`` and ``[a, b, c, c]``
    produce the same root (CVE-2012-2459), so two different snapshots share one manifest and
    the root stops identifying the snapshot.
    """

    @staticmethod
    def _hash_leaf(leaf: str) -> bytes:
        return hashlib.sha256(_LEAF + leaf.encode("utf-8")).digest()

    @staticmethod
    def _hash_node(left: bytes, right: bytes) -> bytes:
        return hashlib.sha256(_NODE + left + right).digest()

    @classmethod
    def root(cls, leaves: list[str]) -> str:
        """64-hex root. An empty tree has a defined root: a table before its first row is a
        real state, and it needs a pinnable manifest like any other."""
        if not leaves:
            return hashlib.sha256(_EMPTY_ROOT_DOMAIN).hexdigest()
        level = [cls._hash_leaf(leaf) for leaf in leaves]
        while len(level) > 1:
            level = cls._next_level(level)
        return level[0].hex()

    @staticmethod
    def _next_level(level: list[bytes]) -> list[bytes]:
        out: list[bytes] = []
        for i in range(0, len(level) - 1, 2):
            out.append(MerkleTree._hash_node(level[i], level[i + 1]))
        if len(level) % 2:
            out.append(level[-1])  # promoted, not duplicated
        return out

    @classmethod
    def proof(cls, leaves: list[str], index: int) -> list[tuple[str, str]]:
        """Sibling hashes from ``leaves[index]`` up to the root, as ``(side, hex)`` pairs.

        A promoted node has no sibling at its level and contributes nothing to the proof.
        """
        if not 0 <= index < len(leaves):
            raise IndexError(f"index {index} outside 0..{len(leaves) - 1}")
        level = [cls._hash_leaf(leaf) for leaf in leaves]
        path: list[tuple[str, str]] = []
        while len(level) > 1:
            sibling = index ^ 1
            if sibling < len(level):
                path.append(("L" if sibling < index else "R", level[sibling].hex()))
            index //= 2
            level = cls._next_level(level)
        return path

    @classmethod
    def verify(cls, leaf: str, index: int, proof: list[tuple[str, str]], root: str) -> bool:
        """Whether ``leaf`` at ``index`` hashes up to ``root`` along ``proof``."""
        node = cls._hash_leaf(leaf)
        for side, sibling_hex in proof:
            sibling = bytes.fromhex(sibling_hex)
            node = cls._hash_node(sibling, node) if side == "L" else cls._hash_node(node, sibling)
        return node.hex() == root
