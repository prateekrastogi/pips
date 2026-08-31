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
