"""Single execution venue, and the stress line that must survive it (ADR-0010).

Dropping Zerodha as a venue is a scope decision. Dropping the cost line derived from its
schedule would be a *gate* change wearing a scope decision's clothes: the P3 bar of
`net SR >= 1.0` is measured against the expensive line precisely because it is expensive, and
deleting it makes the gate easier while looking like tidying up. Rule 10 says that is a human
conversation plus an ADR, never a side effect — so it is pinned here.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml

from pips.ledger.model import load_ledger
from pips.ledger.salvage import NEEDS_COVERAGE

ROOT = Path(__file__).resolve().parents[2]


def _workspace_members() -> list[str]:
    with (ROOT / "Cargo.toml").open("rb") as handle:
        return list(tomllib.load(handle)["workspace"]["members"])


def test_flattrade_is_the_only_broker_adapter_crate() -> None:
    adapters = [m for m in _workspace_members() if "broker-" in m and "broker-protocol" not in m]
    assert adapters == ["rust/crates/broker-flattrade"], adapters


def test_the_venue_agnostic_seam_is_kept() -> None:
    # ADR-0010 defers Zerodha rather than rejecting it; a second adapter must stay an
    # addition, not a rewrite. That is only true while broker-protocol exists.
    assert "rust/crates/broker-protocol" in _workspace_members()


def test_the_high_cost_reference_line_threshold_survives() -> None:
    gates: dict[str, Any] = yaml.safe_load((ROOT / "config" / "gates.yaml").read_text())
    assert gates["p3_gate"]["net_sharpe_min_high_cost_line"] == 1.0, (
        "the high-cost stress line is retained at full severity by ADR-0010; lowering or "
        "removing it is a gate change, not a scope cut"
    )
    assert gates["p3_gate"]["net_sharpe_min_zero_cost_line"] == 1.5


def test_the_high_cost_golden_row_still_exists_in_the_ledger() -> None:
    ledger = load_ledger(ROOT / "docs" / "ledger")
    row = next((r for r in ledger.contracts if r.id == "C-COST-02"), None)
    assert row is not None, "C-COST-02 carries the high-cost goldens and must not be deleted"
    assert "8.268 bps" in row.title


def test_the_retired_venue_is_no_longer_a_covered_need() -> None:
    assert "M23 broker-zerodha adapter" not in NEEDS_COVERAGE
    assert "M23 broker-flattrade adapter" in NEEDS_COVERAGE
