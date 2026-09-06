"""A+ (`BLK-0005`): a three-component pre-rank picks the 500 for capture, with two safeguards.

WHY. `build_shortlist` scores with `liquidity_scores`, whose `_unmeasurable` refuses a missing
spread. Spread comes from 1-second capture, which is budgeted for the 500 names the shortlist
selects -- so with no spread anywhere the shortlist admits nobody. `shortlist.py` forbids a second
score, because using M7's own score is what made the 500 a superset of every registered universe
BY CONSTRUCTION. Both were deliberate. The owner chose A+ on 2026-09-05: break the circle with a
pre-rank, and replace the by-construction guarantee with something CHECKED and something that
CORRECTS.

WHAT THIS IS NOT. Not a liquidity score. It has no spread term and carries a different type and
name so nothing downstream can mistake it for one. It picks names for CAPTURE -- which data will
exist -- never for trading. It invents no weights: the three it uses are §4.1's own, with the
spread term omitted, because a new weighting would be a free parameter fitted after seeing the
data, which is exactly what `top_n` refuses an unregistered N to prevent.

THE COST, plainly. The 500 are chosen by an ordering that omits the term with the second-largest
weight (spread, -0.75). A heavily traded but persistently wide name can enter the 500 and then fail
the real score -- cheap, it just wastes capture. A tight but modest-volume name can MISS the 500 and
never get the data that would have shown it -- expensive, because a name missing from the archive
is missing for as long as the archive runs. `superset_breaches` measures the first kind of error
each refresh; `exploration_picks` is the only thing that ever corrects the second.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# One z-score implementation in this package, not two. `_z` is private to `liquidity` because
# nothing else needed it; this is the second caller, and copying it would give the pre-rank a
# subtly different notion of "cross-sectional" than the score it feeds into.
from pips.universe.liquidity import WEIGHTS, _z

__all__ = [
    "PRERANK_WEIGHTS",
    "DailyStats",
    "PreRank",
    "exploration_picks",
    "prerank_for_capture",
    "superset_breaches",
]

PRERANK_WEIGHTS: Mapping[str, float] = {k: v for k, v in WEIGHTS.items() if k != "relative_spread"}
"""§4.1's weights with the spread term removed -- derived from `WEIGHTS`, never restated, so the
two cannot drift apart."""


@dataclass(frozen=True)
class DailyStats:
    """One symbol's DAILY-derivable liquidity inputs. Deliberately has no spread field."""

    symbol: str
    median_rupee_volume: float
    amihud: float
    gap_rate: float


@dataclass(frozen=True)
class PreRank:
    """Names picked for CAPTURE by the three-component pre-rank. NOT a liquidity score.

    This decides which names get 1-second data acquired. It decides nothing about trading: the
    universe is chosen later, by `liquidity_scores`, over the four components -- including the
    spread this pre-rank could not see. Treating `selected` as a universe would trade on a score
    with its second-largest term missing.
    """

    selected: tuple[str, ...]
    ranked: tuple[str, ...]
    """Every admissible name in pre-rank order, best first. `exploration_picks` reads the tail."""
    excluded: Mapping[str, str]
    n_admissible: int
    as_of: date | None = None


def _unmeasurable(s: DailyStats) -> str:
    """Why a name cannot be pre-ranked, or ``""``.

    Mirrors `shortlist._unmeasurable` and, like it, names the field rather than returning a bool.
    """
    if not math.isfinite(s.median_rupee_volume) or s.median_rupee_volume <= 0:
        return f"median_rupee_volume is not a positive finite number ({s.median_rupee_volume})"
    for field in ("amihud", "gap_rate"):
        value = getattr(s, field)
        if not math.isfinite(value):
            # Not defaulted: a missing component read as average is the flattering direction.
            return f"{field} is not finite ({value})"
    return ""


def prerank_for_capture(
    population: Sequence[DailyStats], *, n: int, as_of: date | None = None
) -> PreRank:
    """The ``n`` names the three daily components rank highest, for capture. ``n`` is a maximum."""
    excluded: dict[str, str] = {}
    usable: list[DailyStats] = []
    for s in population:
        reason = _unmeasurable(s)
        if reason:
            excluded[s.symbol] = reason
        else:
            usable.append(s)
    if not usable:
        return PreRank((), (), excluded, 0, as_of)

    z = {
        "median_rupee_volume": _z({s.symbol: math.log(s.median_rupee_volume) for s in usable}),
        "amihud": _z({s.symbol: s.amihud for s in usable}),
        "gap_rate": _z({s.symbol: s.gap_rate for s in usable}),
    }
    score = {
        s.symbol: sum(PRERANK_WEIGHTS[c] * z[c][s.symbol] for c in PRERANK_WEIGHTS) for s in usable
    }
    # Ties break on the symbol -- the same rule `top_n` uses -- so the cut falls the same way
    # every run (rule 1).
    ranked = tuple(sorted(score, key=lambda sym: (-score[sym], sym)))
    return PreRank(ranked[: max(n, 0)], ranked, excluded, len(usable), as_of)


def superset_breaches(*, universe: Sequence[str], shortlist: Sequence[str]) -> tuple[str, ...]:
    """Universe names that were NOT in the shortlist that acquired their data. Empty is the pass.

    What `shortlist.py` used to guarantee by construction -- "a name cannot enter U300 without
    already being inside the 500" -- is now OBSERVED each refresh. A breach means a name is being
    traded on a spread nobody captured for it, and the reader gets the name, not a boolean.
    """
    return tuple(sorted(set(universe) - set(shortlist)))


def exploration_picks(
    ranked: Sequence[str], *, cut: int, budget: int, refresh: date, band_end: int | None = None
) -> tuple[str, ...]:
    """``budget`` names just OUTSIDE the cut, rotating deterministically by refresh date.

    The pre-rank's expensive error is the false negative: a tight, modest-volume name that never
    makes the 500 and so never gets the spread data that would have promoted it. Nothing about the
    three components can find that name -- only capturing it can. So each refresh spends a small
    budget on the tail, and the window ADVANCES by ``budget`` per week, which covers the whole tail
    in ``ceil(len(tail) / budget)`` refreshes rather than orbiting the same few names.

    Deterministic in ``refresh`` (rule 1): rotating is not the same as random. A budget that covers
    the whole tail returns the tail once.
    """
    # ``band_end`` bounds the pool to ranks (cut, band_end]: OWNER DECISION 2026-09-06, 501-1,000.
    # A name at rank 2,400 will not qualify on four components; the budget belongs near the cut.
    tail = tuple(ranked[cut:] if band_end is None else ranked[cut:band_end])
    if budget <= 0 or not tail:
        return ()
    if budget >= len(tail):
        return tail
    offset = ((refresh.toordinal() // 7) * budget) % len(tail)
    return tuple(tail[(offset + i) % len(tail)] for i in range(budget))


def _gap_config(path: Path) -> tuple[float, int]:
    """`config/universe/gap_rate.yaml` -> (threshold, lookback_sessions).

    Both required: the pre-rank has no built-in value for either.
    """
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        return float(raw["threshold"]), int(raw["lookback_sessions"])
    except KeyError as missing:
        raise ValueError(
            f"{path}: missing {missing} -- the pre-rank takes no built-in value"
        ) from None


def _exploration_policy(path: Path) -> tuple[int, int, bool, str]:
    """`config/universe/prerank.yaml` -> (budget, band_end, active, activation_condition)."""
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        e = raw["exploration"]
        return (
            int(e["budget"]),
            int(e["band_end"]),
            bool(e["active"]),
            str(e["activation_condition"]),
        )
    except KeyError as missing:
        raise ValueError(
            f"{path}: missing {missing} in `exploration` -- no built-in policy"
        ) from None


def main(argv: list[str] | None = None) -> int:
    """CLI: ``pips universe prerank <root> --as-of YYYY-MM-DD [--n 500] [--config P]``.

    ``--prerank-config Q`` names the exploration policy (``config/universe/prerank.yaml``).

    The daily panel (`pips daily promote`) -> `DailyStats` over the configured lookback ->
    `prerank_for_capture` -> ONE artifact at ``<root>/universes/prerank-<as_of>.json``. The
    artifact is append-only: the same as-of twice is a refusal, because a re-run that would pick a
    different 500 for the same day is a fact to be looked at, not a file to be replaced.
    """
    import argparse
    import json
    import os
    import sys

    from pips.core.fsguard import writable_directory
    from pips.data.pit.explain import jump_explainer
    from pips.universe.daily_stats import daily_stats_from_panel
    from pips.universe.shortlist import CAPTURE_SHORTLIST_N

    parser = argparse.ArgumentParser(prog="pips universe prerank")
    parser.add_argument("data_root", nargs="?", default=None, help="defaults to $PIPS_DATA_ROOT")
    parser.add_argument(
        "--as-of",
        required=True,
        help="the last session the window may see; NOT defaulted to today, so the artifact "
        "names the date it was built for rather than the date somebody ran it",
    )
    parser.add_argument(
        "--n", type=int, default=CAPTURE_SHORTLIST_N, help="a MAXIMUM, not a target"
    )
    parser.add_argument(
        "--config", default="config/universe/gap_rate.yaml", help="threshold + lookback_sessions"
    )
    parser.add_argument(
        "--prerank-config",
        default="config/universe/prerank.yaml",
        help="exploration policy: budget, band_end, active + its activation condition",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    root = (
        Path(args.data_root)
        if args.data_root
        else Path(os.environ.get("PIPS_DATA_ROOT", "/srv/pips"))
    )
    as_of = date.fromisoformat(args.as_of)
    refusal = writable_directory(root / "universes")
    if refusal is not None:
        print(f"prerank: {refusal}", file=sys.stderr)
        return 2
    panel = root / "daily" / "bars_1d.parquet"
    if not panel.exists():
        print(f"prerank: no daily panel at {panel} — nothing to rank.")
        print(
            "    That is not a pass. Run `pips daily promote` first (ops/runbooks/backfill.md §5)."
        )
        return 0
    target = root / "universes" / f"prerank-{as_of.isoformat()}.json"
    if target.exists():
        print(
            f"prerank: {target} already exists — the artifact is append-only. A different "
            "selection for the same as-of is a fact to be looked at, not a file to be replaced.",
            file=sys.stderr,
        )
        return 1
    threshold, lookback = _gap_config(Path(args.config))
    explain = jump_explainer(root / "pit")
    if explain is None:
        print(
            f"prerank: no PIT store at {root / 'pit'} — corporate-action gaps are counted as "
            "gaps in gap_rate, which is the conservative direction (a CA name looks jumpier)."
        )
    report = daily_stats_from_panel(
        panel, as_of=as_of, lookback_sessions=lookback, gap_threshold=threshold, explain=explain
    )
    pre = prerank_for_capture(report.stats, n=args.n, as_of=as_of)
    excluded = {**report.excluded, **pre.excluded}
    budget, band_end, active, condition = _exploration_policy(Path(args.prerank_config))
    if active:
        explore = exploration_picks(
            pre.ranked, cut=len(pre.selected), budget=budget, refresh=as_of, band_end=band_end
        )
    else:
        explore = ()
        print(
            f"prerank: exploration inactive ({budget}/week over ranks {args.n + 1}-{band_end}): "
            f"{condition}"
        )
    artifact = {
        "as_of": as_of.isoformat(),
        "n": args.n,
        "n_admissible": pre.n_admissible,
        "lookback_sessions": lookback,
        "gap_threshold": threshold,
        "config": str(args.config),
        "panel": str(panel),
        "selected": list(pre.selected),
        "ranked": list(pre.ranked),
        "isins": {symbol: report.isins[symbol] for symbol in pre.ranked},
        "exploration": list(explore),
        "exploration_policy": {"budget": budget, "band_end": band_end, "active": active},
        "excluded": dict(sorted(excluded.items())),
        "weights": dict(PRERANK_WEIGHTS),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"prerank as of {as_of.isoformat()}: {len(pre.selected)} selected of {pre.n_admissible} "
        f"admissible (n={args.n}), {len(excluded)} excluded, {len(explore)} exploration -> {target}"
    )
    if len(pre.selected) < args.n:
        print(
            f"    n is a maximum: {pre.n_admissible} admissible name(s), so {len(pre.selected)} "
            "selected. Fewer is a valid output; a padded list would not be."
        )
    return 0
