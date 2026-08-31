"""Data quality checks  (§6 M5, §3.4).

Each check returns findings rather than raising, so one bad bar does not hide the rest of a
session's problems. Findings carry a severity, and ``QUARANTINE`` means the record does not
enter silver -- it goes to the quarantine zone **with its reason**, never silently dropped and
never silently kept.

**The hardest judgement here is what "missing" means**, and the M3 probe settled it: Breeze
OMITS untraded minutes rather than zero-filling them. Absence is therefore the normal case, and
a naive gap check would flag every session of every name that is not the most liquid on the
exchange -- burying the real findings under thousands of false ones. What distinguishes a real
gap is corroboration from outside the bars themselves: the manifest knows whether the fetch
succeeded, and "no data because nothing traded" is evidence while "no data because we never
got an answer" is a hole.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from pips.data.breeze.ingest import NormalizedBar
from pips.data.pit.corporate_actions import JumpVerdict

__all__ = [
    "Finding",
    "Severity",
    "check_bar_sanity",
    "check_decimal_shift",
    "check_monotonic_labels",
    "check_raw_row_order",
    "check_session_coverage",
    "check_spikes",
    "check_unexplained_ratio_jump",
]

# A price this far from its neighbours, that then RETURNS, is a misplaced decimal point rather
# than a market event. 10x is the classic vendor error; the band is generous around it.
_DECIMAL_LOW = Decimal("8")
_DECIMAL_HIGH = Decimal("12")

# Below this fraction of the expected minutes, a session is truncated rather than thin.
_COVERAGE_FLOOR = Decimal("0.2")

# A ratio this close to a common split/bonus is a corporate action until proven otherwise.
_ACTION_RATIOS = (Decimal(2), Decimal(3), Decimal(4), Decimal(5), Decimal(10))
_RATIO_TOLERANCE = Decimal("0.02")


class Severity(StrEnum):
    """What a finding means for the record."""

    INFO = "INFO"
    WARN = "WARN"
    QUARANTINE = "QUARANTINE"


@dataclass(frozen=True)
class Finding:
    """One problem, with enough detail to act on without re-deriving it."""

    check: str
    severity: Severity
    detail: str
    label: str | None = None


def check_bar_sanity(bars: list[NormalizedBar]) -> list[Finding]:
    """OHLC internal consistency and positivity.

    Zero volume is deliberately NOT an error: §3.4 is explicit that a zero-volume bar is not a
    missing bar, and flagging it would quarantine exactly the quiet periods worth studying.
    """
    findings: list[Finding] = []
    for b in bars:
        label = b.close_label.isoformat()
        if min(b.open_paise, b.high_paise, b.low_paise, b.close_paise) <= 0:
            findings.append(
                Finding("bar_sanity", Severity.QUARANTINE, "non-positive price in bar", label)
            )
            continue
        if b.high_paise < max(b.open_paise, b.close_paise):
            findings.append(
                Finding(
                    "bar_sanity",
                    Severity.QUARANTINE,
                    f"high {b.high_paise} is below open/close ({b.open_paise}/{b.close_paise})",
                    label,
                )
            )
        elif b.low_paise > min(b.open_paise, b.close_paise):
            findings.append(
                Finding(
                    "bar_sanity",
                    Severity.QUARANTINE,
                    f"low {b.low_paise} is above open/close ({b.open_paise}/{b.close_paise})",
                    label,
                )
            )
        elif b.low_paise > b.high_paise:
            findings.append(Finding("bar_sanity", Severity.QUARANTINE, "low above high", label))
        if b.volume < 0:
            findings.append(
                Finding("bar_sanity", Severity.QUARANTINE, f"negative volume {b.volume}", label)
            )
    return findings


def check_monotonic_labels(bars: list[NormalizedBar]) -> list[Finding]:
    """Labels must strictly increase. Duplicates and reordering both corrupt every window."""
    findings: list[Finding] = []
    for a, b in pairwise(bars):
        if b.close_label == a.close_label:
            findings.append(
                Finding(
                    "label_order",
                    Severity.QUARANTINE,
                    f"duplicate label {b.close_label.isoformat()}",
                    b.close_label.isoformat(),
                )
            )
        elif b.close_label < a.close_label:
            findings.append(
                Finding(
                    "label_order",
                    Severity.QUARANTINE,
                    f"label {b.close_label.isoformat()} precedes {a.close_label.isoformat()}",
                    b.close_label.isoformat(),
                )
            )
    return findings


def check_session_coverage(
    bars: list[NormalizedBar], expected_minutes: int, fetch_succeeded: bool
) -> list[Finding]:
    """Whether a session has plausibly complete coverage.

    ``fetch_succeeded`` comes from the backfill manifest, and it is what makes this check
    possible at all. Inside the bars, "nothing traded" and "we never got an answer" look
    identical; only the manifest can tell them apart, and they are not the same claim.
    """
    if not fetch_succeeded:
        return [
            Finding(
                "session_coverage",
                Severity.QUARANTINE,
                "session has no data and the fetch was not fetched successfully — this is a "
                "hole, not a quiet market",
            )
        ]
    if expected_minutes <= 0:
        return []
    ratio = Decimal(len(bars)) / Decimal(expected_minutes)
    if ratio < _COVERAGE_FLOOR:
        return [
            Finding(
                "session_coverage",
                Severity.QUARANTINE,
                f"only {len(bars)} of ~{expected_minutes} expected minutes present "
                f"({ratio:.1%}) — truncated response rather than thin trading",
            )
        ]
    return []


def check_spikes(bars: list[NormalizedBar], max_move_bps: int) -> list[Finding]:
    """Bar-to-bar close moves beyond a plausible bound."""
    findings: list[Finding] = []
    for a, b in pairwise(bars):
        if a.close_paise <= 0:
            continue
        move = abs(Decimal(b.close_paise - a.close_paise) / Decimal(a.close_paise)) * 10_000
        if move > max_move_bps:
            findings.append(
                Finding(
                    "spike",
                    Severity.QUARANTINE,
                    f"{move:.0f} bps move into {b.close_label.isoformat()}",
                    b.close_label.isoformat(),
                )
            )
    return findings


def check_decimal_shift(bars: list[NormalizedBar]) -> list[Finding]:
    """A price ~10x its neighbours that RETURNS -- a misplaced decimal point.

    The return is the whole discriminator. A price that steps up and stays there is a market
    event however large; only a jump that reverts looks like a decimal error. Naming it as one
    matters: flagged merely as a spike it reads as a market event, and the fix would be to
    delete the bar rather than correct it.
    """
    findings: list[Finding] = []
    for previous, current, following in zip(bars, bars[1:], bars[2:], strict=False):
        if previous.close_paise <= 0 or following.close_paise <= 0:
            continue
        up = Decimal(current.close_paise) / Decimal(previous.close_paise)
        down = Decimal(current.close_paise) / Decimal(following.close_paise)
        shifted_up = _DECIMAL_LOW <= up <= _DECIMAL_HIGH and _DECIMAL_LOW <= down <= _DECIMAL_HIGH
        shifted_down = (
            _DECIMAL_LOW <= 1 / up <= _DECIMAL_HIGH and _DECIMAL_LOW <= 1 / down <= _DECIMAL_HIGH
        )
        if shifted_up or shifted_down:
            findings.append(
                Finding(
                    "decimal_shift",
                    Severity.QUARANTINE,
                    f"probable decimal shift at {current.close_label.isoformat()}: price "
                    f"{current.close_paise} against neighbours {previous.close_paise} and "
                    f"{following.close_paise}",
                    current.close_label.isoformat(),
                )
            )
    return findings


def check_unexplained_ratio_jump(
    previous_close_paise: int,
    first_open_paise: int,
    verdict: JumpVerdict | None,
) -> list[Finding]:
    """An overnight jump at a common split/bonus ratio that no known action accounts for.

    Quarantined rather than adjusted: adjusting on a guess silently corrupts every return
    crossing the date, in a way no later check can detect, because the adjusted series looks
    perfectly well-formed.

    ``verdict`` comes from M6's PIT corporate-action master, which answers whether a KNOWN
    action accounts for THIS jump. It replaced a list of declared actions and a bare
    ``if known_actions: return []`` — so any action on the day cleared any jump, and a 1:2
    split sitting next to a 90% collapse waved the collapse through. An action on the day is
    not a licence to accept an arbitrary move.

    ``verdict=None`` means the master was never consulted, and it FAILS CLOSED. Absence of an
    answer is not an answer -- the same rule the websocket gap record follows when it writes
    ``messages_missed: null`` rather than 0.
    """
    if previous_close_paise <= 0 or first_open_paise <= 0:
        return []
    ratio = Decimal(previous_close_paise) / Decimal(first_open_paise)
    for candidate in _ACTION_RATIOS:
        for direction in (candidate, 1 / candidate):
            if abs(ratio - direction) <= _RATIO_TOLERANCE * direction:
                if verdict is not None and verdict.explained:
                    return []
                why = (
                    "the corporate-action master was not consulted"
                    if verdict is None
                    else verdict.reason
                )
                return [
                    Finding(
                        "ratio_jump",
                        Severity.QUARANTINE,
                        f"overnight ratio {ratio:.3f} matches a common corporate action "
                        f"pattern and is unexplained ({why}) — quarantined rather than "
                        "adjusted, because adjusting on a guess corrupts every return "
                        "crossing the date",
                    )
                ]
    return []


def check_raw_row_order(payload_rows: list[dict[str, object]]) -> list[Finding]:
    """Whether the VENDOR returned rows in order, before normalization sorts them.

    ``normalize_candles`` sorts by label, which downstream code needs -- but a sort is a
    silent repair, and it hides the thing it repairs. Out-of-order rows are worth seeing: they
    suggest a partial or merged response rather than a clean one, and by the time the bars
    exist that evidence is gone. So the check runs on the raw rows and the normalizer keeps
    sorting, which is the same shape as the websocket gap record -- repair the data, but
    record that a repair happened.
    """
    stamps = [str(row.get("datetime", "")) for row in payload_rows]
    findings: list[Finding] = []
    for a, b in pairwise(stamps):
        if b == a:
            findings.append(
                Finding("label_order", Severity.QUARANTINE, f"duplicate raw row at {b}", b)
            )
        elif b < a:
            findings.append(
                Finding(
                    "label_order",
                    Severity.QUARANTINE,
                    f"vendor returned rows out of order: {b} follows {a} — the normalizer "
                    "sorts them, so this is the only place the disorder is visible",
                    b,
                )
            )
    return findings
