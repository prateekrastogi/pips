"""Bitemporal PIT store and Merkle snapshot manifests [C-DATA-01] [C-DATA-02] (§3.4, §6 M6).

Two clocks, and the difference between them is the whole point. **Valid time** is when a fact
was true of the world; **knowledge time** is when we knew it. A backtest must read the world as
we knew it then, not as we know it now, or it trades on information that had not arrived.

§6 M6's Verify is the strongest data guarantee in the project: *as-of reads are byte-identical
regardless of later snapshots*. Not "logically equivalent" — byte-identical, so a result can be
tied to a snapshot root and re-derived years later.

§3.4 says corrections create a new knowledge-time version and never an overwrite. That is what
makes survivorship auditable: a name that has since been delisted, renamed, or had its data
corrected is still visible exactly as it appeared at the time.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from pips.data.pit.store import MerkleTree, PitRecord, PitStore

D = date


def instrument(store: PitStore, key: str, symbol: str, known: date, valid: date) -> None:
    store.append(
        PitRecord(
            table="instruments",
            key=key,
            valid_from=valid,
            known_from=known,
            payload={"symbol": symbol, "isin": f"IN{key}"},
        )
    )


@pytest.fixture
def store(tmp_path: Path) -> PitStore:
    return PitStore(tmp_path / "pit")


# ------------------------------------------------- the headline guarantee ---------------


def test_an_as_of_read_is_byte_identical_after_later_snapshots(store: PitStore) -> None:
    """The §6 M6 Verify, taken literally.

    A read as of 2026-06-30 must serialize to the same bytes today and after every later
    snapshot has landed. Anything weaker cannot anchor a result to a snapshot root, and
    without that anchor a result is not evidence (rule 3).
    """
    instrument(store, "1", "RELIANCE", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    instrument(store, "2", "INFY", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    before = json.dumps(
        [r.model_dump(mode="json") for r in store.as_of("instruments", known_on=D(2026, 6, 30))],
        sort_keys=True,
    )

    # Everything that could disturb it: new names, corrections, delistings.
    instrument(store, "3", "TCS", known=D(2026, 7, 1), valid=D(2026, 7, 1))
    store.correct(
        "instruments", "1", known_from=D(2026, 7, 2), payload={"symbol": "RELIND", "isin": "IN1"}
    )
    store.close("instruments", "2", known_from=D(2026, 7, 3))

    after = json.dumps(
        [r.model_dump(mode="json") for r in store.as_of("instruments", known_on=D(2026, 6, 30))],
        sort_keys=True,
    )
    assert after == before, "an as-of read must not move when later snapshots land"


def test_the_snapshot_root_is_stable_for_a_past_knowledge_date(store: PitStore) -> None:
    instrument(store, "1", "RELIANCE", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    root = store.snapshot_root("instruments", known_on=D(2026, 6, 30))
    instrument(store, "9", "LATER", known=D(2026, 8, 1), valid=D(2026, 8, 1))
    assert store.snapshot_root("instruments", known_on=D(2026, 6, 30)) == root


def test_the_snapshot_root_moves_when_the_snapshot_does(store: PitStore) -> None:
    instrument(store, "1", "RELIANCE", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    root = store.snapshot_root("instruments", known_on=D(2026, 6, 30))
    instrument(store, "2", "INFY", known=D(2026, 6, 2), valid=D(2026, 1, 1))
    assert store.snapshot_root("instruments", known_on=D(2026, 6, 30)) != root


# ------------------------------------------------- corrections, not overwrites ----------


def test_a_correction_creates_a_new_version_and_keeps_the_old(store: PitStore) -> None:
    # §3.4. The old value is what a backtest run before the correction actually saw, so
    # deleting it makes that run unreproducible.
    instrument(store, "1", "OLDNAME", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    store.correct("instruments", "1", known_from=D(2026, 7, 1), payload={"symbol": "NEWNAME"})

    before = store.as_of("instruments", known_on=D(2026, 6, 15))
    after = store.as_of("instruments", known_on=D(2026, 7, 15))
    assert before[0].payload["symbol"] == "OLDNAME"
    assert after[0].payload["symbol"] == "NEWNAME"


def test_reading_the_past_shows_what_we_believed_then_errors_included(store: PitStore) -> None:
    # The uncomfortable one, and the reason knowledge time exists. If a value was wrong on the
    # day, the backtest that ran on the day saw the wrong value — and reproducing that run
    # means reproducing the error, not correcting it.
    instrument(store, "1", "WRONG", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    store.correct("instruments", "1", known_from=D(2026, 7, 1), payload={"symbol": "RIGHT"})
    assert store.as_of("instruments", known_on=D(2026, 6, 10))[0].payload["symbol"] == "WRONG"


def test_nothing_is_ever_removed_from_the_log(store: PitStore) -> None:
    instrument(store, "1", "A", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    store.correct("instruments", "1", known_from=D(2026, 7, 1), payload={"symbol": "B"})
    store.close("instruments", "1", known_from=D(2026, 8, 1))
    assert len(store.all_records("instruments")) == 3


# ------------------------------------------------------------ survivorship --------------


def test_a_delisted_name_still_appears_in_an_earlier_as_of_read(store: PitStore) -> None:
    instrument(store, "1", "ALIVE", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    instrument(store, "2", "DOOMED", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    store.close("instruments", "2", known_from=D(2026, 7, 1))

    assert {r.key for r in store.as_of("instruments", known_on=D(2026, 6, 15))} == {"1", "2"}
    assert {r.key for r in store.as_of("instruments", known_on=D(2026, 7, 15))} == {"1"}


def test_the_survivorship_audit_names_what_disappeared(store: PitStore) -> None:
    # §6 M6's second Verify. "Present-day constituents projected backward" is the first line of
    # §7's rejection list, and this query is how you catch yourself doing it.
    instrument(store, "1", "ALIVE", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    instrument(store, "2", "DOOMED", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    store.close("instruments", "2", known_from=D(2026, 7, 1))

    audit = store.survivorship_audit("instruments", earlier=D(2026, 6, 15), later=D(2026, 7, 15))
    assert audit.disappeared == ["2"]
    assert audit.survived == ["1"]
    assert "1 of 2" in audit.describe()


def test_an_audit_over_an_unchanged_window_reports_no_loss(store: PitStore) -> None:
    instrument(store, "1", "ALIVE", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    audit = store.survivorship_audit("instruments", earlier=D(2026, 6, 15), later=D(2026, 7, 15))
    assert audit.disappeared == []


def test_an_inverted_audit_window_is_refused(store: PitStore) -> None:
    with pytest.raises(ValueError, match="earlier"):
        store.survivorship_audit("instruments", earlier=D(2026, 7, 1), later=D(2026, 6, 1))


# ------------------------------------------------------------ Merkle -------------------


def test_identical_content_gives_an_identical_root() -> None:
    assert MerkleTree.root(["a", "b", "c"]) == MerkleTree.root(["a", "b", "c"])


def test_any_change_moves_the_root() -> None:
    base = MerkleTree.root(["a", "b", "c"])
    assert MerkleTree.root(["a", "b", "d"]) != base
    assert MerkleTree.root(["a", "b"]) != base
    assert MerkleTree.root(["a", "c", "b"]) != base, "order is part of the content"


def test_an_empty_tree_has_a_defined_root() -> None:
    # An empty snapshot is a real state — a table before its first row — and needs a root that
    # can be pinned like any other.
    assert len(MerkleTree.root([])) == 64


def test_an_odd_leaf_count_is_handled() -> None:
    # The classic Merkle bug: an odd level duplicates its last node, and a naive duplication
    # makes [a, b, b] indistinguishable from [a, b]. These must differ.
    assert MerkleTree.root(["a", "b", "b"]) != MerkleTree.root(["a", "b"])


def test_a_proof_verifies_against_the_root() -> None:
    leaves = [f"leaf{i}" for i in range(7)]
    root = MerkleTree.root(leaves)
    proof = MerkleTree.proof(leaves, index=3)
    assert MerkleTree.verify(leaves[3], index=3, proof=proof, root=root)
    assert not MerkleTree.verify("tampered", index=3, proof=proof, root=root)


# ------------------------------------------------------------ valid time ---------------
# The clock the first pass forgot to test. Knowledge time was covered from the start because
# it is the headline; valid time was implemented and then simply believed.


def test_a_fact_not_yet_valid_is_withheld_even_though_it_is_known(store: PitStore) -> None:
    """An index change announced in June and effective in September.

    We KNOW about it in June — that is knowledge time. It is not TRUE until September — that
    is valid time. Trading it in July because we had read the announcement is lookahead of the
    ordinary, plausible kind, and only the second clock catches it.
    """
    store.append(
        PitRecord(
            table="membership",
            key="NEWENTRANT",
            known_from=D(2026, 6, 1),
            valid_from=D(2026, 9, 1),
            payload={"index": "NIFTY50"},
        )
    )
    assert store.as_of("membership", known_on=D(2026, 7, 1)) == []
    assert len(store.as_of("membership", known_on=D(2026, 9, 15))) == 1


def test_valid_on_can_be_asked_independently_of_known_on(store: PitStore) -> None:
    store.append(
        PitRecord(
            table="membership",
            key="NEWENTRANT",
            known_from=D(2026, 6, 1),
            valid_from=D(2026, 9, 1),
            payload={"index": "NIFTY50"},
        )
    )
    # As we understood things in July, asking about September: the change is in force.
    assert len(store.as_of("membership", known_on=D(2026, 7, 1), valid_on=D(2026, 9, 15))) == 1
    # But as we understood things in May, that same September question has no answer yet.
    assert store.as_of("membership", known_on=D(2026, 5, 1), valid_on=D(2026, 9, 15)) == []


def test_valid_on_defaults_to_known_on(store: PitStore) -> None:
    store.append(
        PitRecord(
            table="membership",
            key="X",
            known_from=D(2026, 6, 1),
            valid_from=D(2026, 9, 1),
            payload={},
        )
    )
    for day in (D(2026, 7, 1), D(2026, 9, 15)):
        assert store.as_of("membership", known_on=day) == store.as_of(
            "membership", known_on=day, valid_on=day
        )


# ------------------------------------------------------- knowledge moves forward --------


def test_backdating_a_knowledge_date_is_refused(store: PitStore) -> None:
    """The guard that keeps a past as-of read from moving.

    Byte-identity is not a property of the read function alone — it is a property of the read
    function AND a log that only grows forward in knowledge time. Allow a row to be inserted
    with an earlier known_from and yesterday's snapshot silently changes, with the read code
    untouched and every test above still green.
    """
    instrument(store, "1", "A", known=D(2026, 7, 1), valid=D(2026, 1, 1))
    with pytest.raises(ValueError, match="only moves forward"):
        instrument(store, "1", "B", known=D(2026, 6, 1), valid=D(2026, 1, 1))


def test_late_arriving_information_is_recorded_with_the_date_it_arrived(store: PitStore) -> None:
    # The legitimate version of the same situation, and the reason the refusal above is not
    # merely restrictive: a fact true since January, learned in July, is expressible.
    instrument(store, "1", "A", known=D(2026, 7, 1), valid=D(2026, 1, 1))
    store.append(
        PitRecord(
            table="instruments",
            key="2",
            known_from=D(2026, 7, 5),
            valid_from=D(2026, 1, 15),
            payload={"symbol": "LATE"},
        )
    )
    assert {r.key for r in store.as_of("instruments", known_on=D(2026, 7, 10))} == {"1", "2"}


def test_a_second_key_may_be_appended_behind_another_keys_clock(store: PitStore) -> None:
    # The forward-only rule is PER KEY. Making it global would mean ingesting tables in
    # knowledge order, which no real backfill can promise.
    instrument(store, "1", "A", known=D(2026, 7, 1), valid=D(2026, 1, 1))
    instrument(store, "2", "B", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    assert len(store.as_of("instruments", known_on=D(2026, 7, 10))) == 2


def test_amending_a_key_that_was_never_appended_is_refused(store: PitStore) -> None:
    with pytest.raises(KeyError, match="ghost"):
        store.correct("instruments", "ghost", known_from=D(2026, 7, 1), payload={})
    with pytest.raises(KeyError, match="ghost"):
        store.close("instruments", "ghost", known_from=D(2026, 7, 1))


def test_an_unknown_table_reads_empty_rather_than_raising(store: PitStore) -> None:
    assert store.as_of("nothing_here", known_on=D(2026, 7, 1)) == []
    assert store.all_records("nothing_here") == []
    assert len(store.snapshot_root("nothing_here", known_on=D(2026, 7, 1))) == 64


# ------------------------------------------------------------ durability ---------------


def test_the_log_survives_a_reopen_byte_for_byte(tmp_path: Path) -> None:
    # The store is a file, so "byte-identical regardless of later snapshots" has to hold
    # across process boundaries too — an in-memory-only guarantee would be worthless to a
    # backtest run months later.
    path = tmp_path / "pit"
    first = PitStore(path)
    instrument(first, "1", "RELIANCE", known=D(2026, 6, 1), valid=D(2026, 1, 1))
    root = first.snapshot_root("instruments", known_on=D(2026, 6, 30))

    reopened = PitStore(path)
    assert reopened.snapshot_root("instruments", known_on=D(2026, 6, 30)) == root
    assert reopened.as_of("instruments", known_on=D(2026, 6, 30)) == first.as_of(
        "instruments", known_on=D(2026, 6, 30)
    )


# ------------------------------------------------------------ Merkle proofs ------------


@pytest.mark.parametrize("size", range(1, 10))
def test_every_index_proves_against_the_root(size: int) -> None:
    """Every leaf of every size, not one leaf of one size.

    Sizes 1..9 walk the promoted-node path repeatedly (3, 5, 6, 7, 9 all promote at some
    level), which is where an off-by-one in the climb hides. Proving index 3 of 7 once — as
    the first version of this file did — exercises one path out of twenty-nine.
    """
    leaves = [f"leaf{i}" for i in range(size)]
    root = MerkleTree.root(leaves)
    for i in range(size):
        assert MerkleTree.verify(leaves[i], i, MerkleTree.proof(leaves, i), root), (
            f"index {i} of {size} failed"
        )


@pytest.mark.parametrize("size", range(2, 10))
def test_a_proof_does_not_transfer_to_another_index(size: int) -> None:
    leaves = [f"leaf{i}" for i in range(size)]
    root = MerkleTree.root(leaves)
    proof = MerkleTree.proof(leaves, 0)
    assert not MerkleTree.verify(leaves[1], 1, proof, root)


def test_an_out_of_range_proof_is_refused() -> None:
    with pytest.raises(IndexError):
        MerkleTree.proof(["a", "b"], index=2)


# ------------------------------------------------------- the hashing scheme itself ------


def test_the_merkle_scheme_matches_its_golden_vectors() -> None:
    """Pin the scheme, not just its structural properties.

    Every structural test above passes for a whole FAMILY of hashing schemes. A mutation run
    proved it: removing the leaf/node domain-separation prefixes killed no test, because with
    `str` leaves and raw-digest nodes the second-preimage attack those prefixes exist to stop
    is already blocked by the type split. The prefixes stay — defence in depth, and the split
    is an implementation detail that could change — but they were unpinned.

    The gap that actually matters is worse than an unexploited prefix. A snapshot root is
    written down next to a result and checked years later. If the scheme changes for ANY
    reason — a prefix, a digest, a concatenation order — every root ever recorded silently
    stops verifying, and no structural test notices, because the new scheme has all the same
    structural properties. These vectors are what notices. Changing them is changing the
    manifest format, which needs an ADR and a migration, not an edit to this list.
    """
    # (leaves, root) — regenerate ONLY alongside an ADR that changes the manifest format.
    vectors = [
        ([], "c159867e168a52a108f97fc3dc8d0116ca0ec48685975c4bc544998408867dbc"),
        (["a"], "022a6979e6dab7aa5ae4c3e5e45f7e977112a7e63593820dbec1ec738a24f93c"),
        (["a", "b"], "b137985ff484fb600db93107c77b0365c80d78f5b429ded0fd97361d077999eb"),
        (["a", "b", "c"], "36642e73c2540ab121e3a6bf9545b0a24982cd830eb13d3cd19de3ce6c021ec1"),
        (["a", "b", "c", "d"], "33376a3bd63e9993708a84ddfe6c28ae58b83505dd1fed711bd924ec5a6239f0"),
        (
            [f"leaf{i}" for i in range(7)],
            "4b6939132387c5bf27ebaf5ac122810ce866eb0c7bf44082364b35c06f713aa6",
        ),
    ]
    for leaves, expected in vectors:
        assert MerkleTree.root(leaves) == expected, f"scheme changed for {leaves}"


def test_a_record_leaf_is_pinned_to_its_content() -> None:
    """The other half of the same concern: the leaf encoding.

    A stable tree over an unstable leaf encoding gives an unstable root. This pins the whole
    path from a PitRecord to its snapshot root, so a field added to PitRecord announces itself
    here rather than in a failed verification years later.
    """
    record = PitRecord(
        table="instruments",
        key="1",
        valid_from=D(2026, 1, 1),
        known_from=D(2026, 6, 1),
        payload={"symbol": "RELIANCE"},
    )
    assert record.leaf() == ("65a2ca97cb87cccc8398265ce2fa34a11319994ef96fed79aba20dba6fb1ddc0")


def test_a_future_dated_version_does_not_mask_the_one_in_force(store: PitStore) -> None:
    """The bug this file did not catch, found by the capability master's tests instead.

    `as_of` picked the most recently KNOWN version of a key and only then asked whether it was
    yet valid. So a version recorded today and effective next month hid the one actually in
    force, and the key disappeared from the table altogether — a lookup reporting no data for
    a date that plainly has data. In the broker-capability table that reads as "this broker
    could not trade that day", which is a permission decision made by an ordering mistake.

    Both filters now apply before the choice, which is what bitemporal means: among versions
    known by then AND valid by then, take the most recently known.
    """
    store.append(
        PitRecord(
            table="rules",
            key="cutoff",
            valid_from=D(2026, 1, 1),
            known_from=D(2026, 1, 1),
            payload={"at": "15:00"},
        )
    )
    store.append(
        PitRecord(
            table="rules",
            key="cutoff",
            valid_from=D(2026, 9, 1),  # announced early, effective later
            known_from=D(2026, 8, 20),
            payload={"at": "15:10"},
        )
    )

    in_force = store.as_of("rules", known_on=D(2026, 8, 25))
    assert [r.payload["at"] for r in in_force] == ["15:00"], (
        "the announcement must not displace the rule actually in force"
    )
    assert [r.payload["at"] for r in store.as_of("rules", known_on=D(2026, 9, 2))] == ["15:10"]


def test_a_closure_takes_effect_when_it_happens_not_when_the_key_was_created(
    store: PitStore,
) -> None:
    """A tombstone must not inherit the valid_from of the version it closes.

    `close` copied `valid_from` from the current version, so a security listed in 2020 and
    delisted in 2026 produced a CLOSE record valid from 2020 — reading, under valid-time
    filtering, as though it had never existed at all.

    The collapsed identity clock hid this completely: while knowledge and valid time were the
    same date, the tombstone only ever surfaced once its knowledge date had passed, and its
    valid_from was never consulted independently. Separating the clocks surfaced it
    immediately, in a test about something else.
    """
    store.append(
        PitRecord(
            table="instruments",
            key="1",
            valid_from=D(2020, 1, 1),
            known_from=D(2020, 1, 1),
            payload={"symbol": "OLD"},
        )
    )
    store.close("instruments", "1", known_from=D(2026, 6, 1))

    # It existed in 2021 — reading with everything we know now must still say so.
    live = store.as_of("instruments", known_on=D(9999, 12, 31), valid_on=D(2021, 1, 1))
    assert [r.key for r in live] == ["1"], "delisting in 2026 did not un-list it in 2021"
    assert store.as_of("instruments", known_on=D(9999, 12, 31), valid_on=D(2027, 1, 1)) == []


def test_a_closure_can_be_announced_before_it_takes_effect(store: PitStore) -> None:
    # The same split the capability master needed: learned on one date, effective on another.
    store.append(
        PitRecord(
            table="instruments",
            key="1",
            valid_from=D(2020, 1, 1),
            known_from=D(2020, 1, 1),
            payload={"symbol": "OLD"},
        )
    )
    store.close("instruments", "1", known_from=D(2026, 6, 1), valid_from=D(2026, 9, 1))

    known_everything = D(9999, 12, 31)
    assert store.as_of("instruments", known_on=known_everything, valid_on=D(2026, 7, 1))
    assert store.as_of("instruments", known_on=known_everything, valid_on=D(2026, 10, 1)) == []
