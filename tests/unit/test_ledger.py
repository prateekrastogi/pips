"""The ledger closes the loop between prose, ledger, code and tests (§8.2)."""

from __future__ import annotations

from pathlib import Path

from pips.ledger.check import check_ledger, cited_ids, heading_slugs
from pips.ledger.model import Status, load_ledger

ROOT = Path(__file__).resolve().parents[2]


def test_repo_ledger_is_green() -> None:
    failures = check_ledger(ROOT)
    assert failures == [], "ledger-check must be green in the repo it governs"


def test_every_row_has_a_known_status_and_owner() -> None:
    ledger = load_ledger(ROOT / "docs" / "ledger")
    for row in [*ledger.contracts, *ledger.gates]:
        assert isinstance(row.status, Status)
        assert row.owner_milestone.startswith("M")


def test_ranges_expand() -> None:
    known = ["C-COST-01", "C-COST-02", "C-COST-03", "C-COST-04"]
    assert cited_ids("see [C-COST-01…04] for detail", known) == set(known)


def test_globs_expand_against_known_ids() -> None:
    known = ["C-OMS-01", "C-OMS-02", "C-ID-01"]
    assert cited_ids("the order plane [C-OMS-*]", known) == {"C-OMS-01", "C-OMS-02"}


def test_alphanumeric_ids_are_cited() -> None:
    assert "G-S4-DSR" in cited_ids("gate G-S4-DSR applies", ["G-S4-DSR"])


def test_heading_slugs_are_prefix_matchable() -> None:
    slugs = heading_slugs("### 3.7 Cost model — golden numbers `[C-COST-01…04]`\n")
    assert any(s.startswith("37-cost-model") for s in slugs)


def test_ledger_check_also_enforces_the_harvest_map(tmp_path: Path) -> None:
    # rule 13 only bites if it is wired into the gate. A salvage.yaml that leaves an
    # infrastructure need unanswered must turn `make ledger-check` red, not just fail a
    # unit test nobody runs before writing a connector.
    import shutil

    from pips.ledger.check import check_ledger

    shutil.copy(ROOT / "IMPLEMENTATION.md", tmp_path / "IMPLEMENTATION.md")
    ledger_dir = tmp_path / "docs" / "ledger"
    ledger_dir.mkdir(parents=True)
    for name in ("contracts.yaml", "gates.yaml"):
        shutil.copy(ROOT / "docs" / "ledger" / name, ledger_dir / name)
    # A harvest map that covers nothing at all.
    (ledger_dir / "salvage.yaml").write_text(
        "- id: SAL-0001\n"
        "  component: 'something'\n"
        "  decision: SKIP\n"
        "  covers_needs: ['M4 historical fetcher']\n"
        "  repo: intraday\n"
        "  path: 'a.py'\n"
        "  commit: 'be8186d4262a'\n",
        encoding="utf-8",
    )
    failures = check_ledger(tmp_path)
    assert any("salvage" in f or "no salvage row covers" in f for f in failures), failures


def test_collectability_is_answered_by_pytest_not_by_parsing_its_summary() -> None:
    """A real node id collects; a bogus one does not.

    The first version of this check scanned `pytest --collect-only -q` stdout for the node id
    as a substring. Under pytest 9 that output is a per-file COUNT summary, not a list of node
    ids — so a file-path reference matched by accident while a real `path::test` reference
    could never match. Asking pytest to collect the id is version-independent and answers the
    actual question.
    """
    from pips.ledger.check import uncollectable_nodes

    real = "tests/unit/test_ledger.py::test_repo_ledger_is_green"
    bogus = "tests/unit/test_ledger.py::test_this_does_not_exist"
    assert uncollectable_nodes(ROOT, [real]) == []
    assert uncollectable_nodes(ROOT, [bogus]) == [bogus]
    assert uncollectable_nodes(ROOT, []) == []
