"""GATE-0 data-use authority [G-AUTH-0] (§2.1, ADR-0006, ADR-0010).

Before any live order, either ICICI confirms in writing that Breeze may be used as a
read-only data plane while orders execute elsewhere, or the certified signal feed moves to
the execution broker's entitled feed.

The design point of this module: a record that *claims* the gate is cleared without the
evidence to back it must be impossible to construct, not merely refused at the point of use.
A boolean anyone can flip is not a gate — and a result without a resolvable evidence chain is
not evidence (rule 3).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from pips.core.authority import (
    AuthorityRecord,
    AuthorityStatus,
    SignalFeed,
    load_authority,
)

ROOT = Path(__file__).resolve().parents[3]

GRANTED: dict[str, Any] = {
    "gate": "G-AUTH-0",
    "status": "GRANTED",
    "question_ref": "ops/runbooks/authority.md",
    "filed_on": date(2026, 9, 1),
    "response_received_on": date(2026, 9, 20),
    "response_summary": "ICICI confirmed data-only Breeze use with orders at another broker.",
    "evidence_paths": ["docs/reports/feasibility/gate0-icici-response.pdf"],
    "certified_signal_feed": "BREEZE",
    "notes": "",
}


def record(**over: Any) -> AuthorityRecord:
    return AuthorityRecord.model_validate({**GRANTED, **over})


# ------------------------------------------------------------------ what blocks live ----


def test_an_unfiled_gate_blocks_live_trading() -> None:
    rec = record(
        status="UNFILED",
        filed_on=None,
        response_received_on=None,
        response_summary=None,
        evidence_paths=[],
    )
    assert rec.live_trading_permitted() is False
    assert "not been filed" in (rec.blocking_reason() or "")


def test_a_filed_but_unanswered_gate_blocks_live_trading() -> None:
    rec = record(
        status="FILED_AWAITING_RESPONSE",
        response_received_on=None,
        response_summary=None,
        evidence_paths=["docs/reports/feasibility/gate0-question-sent.eml"],
    )
    assert rec.live_trading_permitted() is False
    assert "awaiting" in (rec.blocking_reason() or "").lower()


def test_a_denial_blocks_live_trading_and_names_the_remedy() -> None:
    rec = record(status="DENIED", response_summary="ICICI declined to confirm data-only use.")
    assert rec.live_trading_permitted() is False
    reason = rec.blocking_reason() or ""
    # ADR-0010 left exactly one fallback; the message must say which, or the operator has to
    # rediscover it under pressure.
    assert "Flattrade" in reason


def test_a_written_grant_clears_the_gate() -> None:
    rec = record()
    assert rec.live_trading_permitted() is True
    assert rec.blocking_reason() is None


def test_switching_the_certified_feed_also_clears_the_gate() -> None:
    # §2.1: the gate is cleared EITHER by the clarification OR by the adapter swap.
    rec = record(
        status="RESOLVED_BY_FEED_SWAP",
        certified_signal_feed="FLATTRADE",
        response_summary="Certified signal feed moved to the execution broker's entitled feed.",
    )
    assert rec.live_trading_permitted() is True


# ------------------------------------------- the claims that must be inexpressible ------


def test_a_grant_without_evidence_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="evidence"):
        record(evidence_paths=[])


def test_a_grant_without_a_filing_date_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="filed_on"):
        record(filed_on=None)


def test_a_grant_without_a_response_date_cannot_be_constructed() -> None:
    with pytest.raises(ValueError, match="response_received_on"):
        record(response_received_on=None)


def test_a_response_cannot_predate_the_question() -> None:
    with pytest.raises(ValueError, match="before"):
        record(response_received_on=date(2026, 8, 1))


def test_a_feed_swap_that_still_names_breeze_cannot_be_constructed() -> None:
    # Claiming the swap resolved the gate while the certified feed is still Breeze is the
    # exact self-contradiction this gate exists to prevent.
    with pytest.raises(ValueError, match="BREEZE"):
        record(status="RESOLVED_BY_FEED_SWAP", certified_signal_feed="BREEZE")


def test_an_unfiled_record_cannot_claim_a_filing_date() -> None:
    with pytest.raises(ValueError, match="UNFILED"):
        record(status="UNFILED", response_received_on=None, response_summary=None)


# ------------------------------------------------------------ the repo's real state -----


def test_the_repo_record_is_valid_and_honest_about_its_state() -> None:
    rec = load_authority(ROOT / "docs" / "reports" / "feasibility" / "gate0-authority.yaml")
    assert rec.gate == "G-AUTH-0"
    # Not yet filed — and the record must say so rather than being absent or optimistic.
    assert rec.status is AuthorityStatus.UNFILED
    assert rec.live_trading_permitted() is False
    assert rec.certified_signal_feed is SignalFeed.BREEZE


def test_the_question_template_the_record_points_at_exists() -> None:
    rec = load_authority(ROOT / "docs" / "reports" / "feasibility" / "gate0-authority.yaml")
    assert (ROOT / rec.question_ref).exists(), (
        "the record points at a question template that is not in the repo"
    )
