"""`config/gates.yaml` cannot claim a gate that nothing enforces (§8.2, `[C-GATE-*]`).

The file opens by calling itself "numeric thresholds the funnel enforces" and asserting that
"every value here has a matching row in docs/ledger/gates.yaml". Both were checkable and one
was false: `min_test_trades`, `pairwise_pnl_corr_max` and both `p3_gate.net_sharpe_min_*` have
no ledger row, and appear nowhere in `python/` either. They are populated numbers that read as
live bars and are enforced by nothing.

The file already states the right principle in the other direction — *"empty values are not
defaults, they are gaps"*. The inverse needs saying too, because it is the more dangerous half:
**a populated value is not a gate unless something reads it.** An empty threshold is obviously
missing; a filled one that nothing consults looks exactly like a gate that passed.

Note that the code is not at risk here. The funnel's bars are bound to `docs/ledger/gates.yaml`
by the ledger-agreement test, so a wrong constant fails. The hazard is the second declaration:
a reader who trusts this file, and a number here drifting from the ledger with nothing to say so.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "gates.yaml"
LEDGER = ROOT / "docs" / "ledger" / "gates.yaml"

# The blocks that hold thresholds, as opposed to bookkeeping.
THRESHOLD_BLOCKS = ("s4_certification", "stress", "p3_gate", "governor")


def config() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return loaded


def ledger_rows() -> dict[str, dict[str, Any]]:
    loaded = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    rows = (
        loaded
        if isinstance(loaded, list)
        else next(v for v in loaded.values() if isinstance(v, list))
    )
    return {r["id"]: r for r in rows}


def threshold_paths() -> list[str]:
    loaded = config()
    return [f"{block}.{key}" for block in THRESHOLD_BLOCKS for key in loaded.get(block, {})]


def test_every_threshold_says_what_enforces_it() -> None:
    """No number may sit in this file without an answer to "what reads this?".

    That question is the whole difference between a gate and a wish, and it cannot be answered
    by looking at the number.
    """
    enforced_by = config()["enforced_by"]

    missing = [path for path in threshold_paths() if path not in enforced_by]
    assert missing == [], f"{missing} are declared with nothing saying what enforces them"


def test_a_threshold_bound_to_a_ledger_row_equals_it() -> None:
    """The second declaration must not drift from the first.

    The funnel reads its bars from `docs/ledger/gates.yaml`, so the CODE is already safe. This
    file is what a person reads, and a number here that quietly disagreed with the enforced one
    would be believed.
    """
    rows = ledger_rows()
    loaded = config()

    for path, enforcer in loaded["enforced_by"].items():
        if not enforcer or not (match := re.search(r"\b(G-[A-Z0-9-]+)\b", str(enforcer))):
            continue
        block, key = path.split(".", 1)
        row = rows[match.group(1)]
        assert loaded[block][key] == row["threshold"]["value"], (
            f"{path} says {loaded[block][key]} and {match.group(1)} enforces "
            f"{row['threshold']['value']}"
        )


def test_a_threshold_enforced_by_nothing_says_so_and_means_it() -> None:
    """`null` has to stay true, or it rots the other way.

    A number wired up later while this still says `null` would understate what the system does
    -- and the next reader, told the bar is not live, would not look for it. So `null` is
    checked against the source: nothing in `python/` may read a key this file calls unenforced.
    """
    source = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "python").rglob("*.py")
    )

    collisions = config()["unread_name_collisions"]
    for path, enforcer in config()["enforced_by"].items():
        if enforcer is not None:
            continue
        key = path.split(".")[-1]
        if key in collisions:
            continue
        assert not re.search(rf"\b{re.escape(key)}\b", source), (
            f"{path} is recorded as enforced by nothing, but `{key}` appears in python/ -- "
            "either it is wired up now and this entry is stale, or the name collides and the "
            "entry needs to say which"
        )


def test_the_four_unenforced_thresholds_are_named() -> None:
    """A regression guard on the finding itself.

    These four are pre-registered intent worth keeping -- deleting them would lose the record
    of what §8.2 says a gate needs. What they must not do is read as live.
    """
    enforced_by = config()["enforced_by"]

    for path in (
        "s4_certification.min_test_trades",
        "s4_certification.pairwise_pnl_corr_max",
        "p3_gate.net_sharpe_min_zero_cost_line",
        "p3_gate.net_sharpe_min_high_cost_line",
    ):
        assert enforced_by[path] is None, f"{path} is now enforced — update the map and this test"


def test_every_declared_name_collision_is_real() -> None:
    """The escape hatch must not become a place to hide a stale entry.

    A collision is claimed precisely when the identifier IS present in `python/` for another
    reason -- so if it is absent, the entry is describing something that no longer exists and
    is silently excusing the key from the check that matters.
    """
    source = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / "python").rglob("*.py")
    )

    for key, why in config()["unread_name_collisions"].items():
        assert re.search(rf"\b{re.escape(key)}\b", source), (
            f"{key} is listed as a name collision but does not appear in python/ at all — "
            "the entry is stale and is excusing the key from the honesty check for nothing"
        )
        assert why, f"{key} is excused from the check with no reason given"


def test_the_declared_governor_is_the_one_the_code_enforces() -> None:
    """`enforced_by` maps this threshold to "C-OBUD-01 (caller-supplied, not read from this
    file)" — an honest label, and prose. The candle cap had the same shape two ticks ago and
    got a test binding the declared value to the constant; this one got the label and no test.

    The failure it closes is the one `config/breeze.yaml` already demonstrated: a number
    declared in a config nothing reads, agreeing with the code by care rather than by check.
    Someone tightening the governor here would change a document; the engine would keep its own
    5, and rule 9's "caps at 5/s" would be true of neither on purpose.
    """
    from pips.selection.order_budget import NSE_RETAIL_BUDGET

    declared = config()["governor"]["orders_per_second_max"]

    assert declared == NSE_RETAIL_BUDGET.global_per_second


def test_the_governor_sits_under_the_legal_threshold_rule_9_names() -> None:
    """Rule 9: "≤10 orders/sec per exchange/segment stays registration-free; engine governor
    caps at 5/s". The governor exists to sit UNDER that, so the two numbers are related, not
    independent — and only one of them is declared in this file."""
    from pips.selection.order_budget import NSE_RETAIL_BUDGET

    assert NSE_RETAIL_BUDGET.legal_per_second == 10
    assert NSE_RETAIL_BUDGET.global_per_second < NSE_RETAIL_BUDGET.legal_per_second


def test_the_governor_numbers_the_config_does_not_declare_are_named() -> None:
    """Three of the four numbers `NSE_RETAIL_BUDGET` carries are code-only: the 2/s per-symbol
    throttle, the ~3000 daily cap, and SEBI's 10/s threshold. Whether this file should declare
    them is a design decision, not something to settle from a test — but a reader comparing the
    config to the engine should not have to discover the gap by counting.
    """
    governor = config()["governor"]

    assert set(governor) == {"orders_per_second_max"}, (
        "the governor block gained or lost a key; if the throttle, the daily cap or the legal "
        "threshold are now declared here, they need binding tests like the one above"
    )
