"""The 1-second capture shortlist: filter for admissibility, score to cut to N (§6 M4).

Forward capture has a fixed price -- 500 symbols x 60 sessions of one-second bars is 690,000
calls, about 7.7 days of quota -- so the width is an input, not an outcome. That single fact
decides the shape of this module, because the two ways to pick symbols fail differently.

A **filter** gives every rejection a nameable reason and can say *I don't know*: a symbol whose
spread was never measured is excluded because it was never measured, not scored on a number
somebody imputed. But its output size is whatever the thresholds happen to admit, which a fixed
call budget cannot use. A **score** takes exactly N, and pays for it by turning missingness into
a middling z-score and by carrying weights -- free parameters that, fitted on the same data
they select from, make the shortlist a trial that has to be counted (rule 4).

So: **filter for admissibility, score only to cut the admissible set down to N.**

The score is M7's :func:`~pips.universe.liquidity.liquidity_scores`, unchanged and unweighted
by anything here. That is the load-bearing choice. The universe is the top N of that same
ordering, so ranking the shortlist by it makes the shortlist a **superset of every registered
universe by construction** -- a name cannot enter U300 without already being inside the 500,
which is the entire reason the number is 500 rather than 300. A second, differently-weighted
score would break that silently, and would be free parameters chosen after seeing the data,
which is what `top_n` refuses an unregistered N to prevent.

The filter, correspondingly, adds no eligibility criteria of its own. It reports the
measurability requirement the scorer already imposes, which `liquidity_scores` applies
silently. Any stricter gate here could reject a name the universe admits -- and that name would
then be traded with no captured data behind it. For the universe a silent exclusion is
tolerable; for acquisition it is not, because the shortlist decides what data will exist, and a
name missing from it is missing from the archive for as long as the archive runs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from pips.universe.liquidity import liquidity_scores

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from pips.universe.liquidity import SymbolStats

__all__ = ["CAPTURE_SHORTLIST_N", "Shortlist", "build_shortlist"]

CAPTURE_SHORTLIST_N: Final = 500
"""How many symbols forward capture records at one second.

**An acquisition width, never a universe size.** It is deliberately absent from
:data:`~pips.universe.liquidity.SUPPORTED_N`: registering it there would make a U500 strategy
runnable, and nobody pre-registered one. This number decides what is *recorded*; that set
decides what is *traded*.

Wider than the widest registered universe (300) on purpose -- the stable-core buffer applied to
data rather than to membership. A shortlist equal to U300 would give every name entering the
universe a cold start with no 1-second history, and forward capture cannot be backfilled to
repair it. The 200 names of headroom are names already being captured before they are needed.
"""


@dataclass(frozen=True)
class Shortlist:
    """What will be captured, what was refused, and why."""

    symbols: tuple[str, ...]
    rejected: Mapping[str, str]
    n_admissible: int
    as_of: date

    @property
    def outranked(self) -> int:
        """Admissible symbols that lost the cut.

        Kept apart from :attr:`rejected` because they are a different event. A name that ranked
        501st is not a data failure, and folding the two together would either make a healthy
        shortlist look like hundreds of broken feeds, or hide real breakages among the merely
        outranked.
        """
        return self.n_admissible - len(self.symbols)


def _unmeasurable(stat: SymbolStats) -> str:
    """Why this symbol cannot be scored, or ``""`` if it can.

    Mirrors ``liquidity._usable`` and differs only in speaking: it names the field. A single
    boolean would send the reader to a debugger, where the field name sends them to the data.
    """
    if not math.isfinite(stat.median_rupee_volume) or stat.median_rupee_volume <= 0:
        # A name that traded nothing has no log-volume, and a floor would invent one.
        return f"median_rupee_volume is not a positive finite number ({stat.median_rupee_volume})"
    for field in ("relative_spread", "amihud", "gap_rate"):
        value = getattr(stat, field)
        if not math.isfinite(value):
            # Not defaulted to zero: a missing spread read as zero makes an illiquid name look
            # tight, which is the flattering direction and the one that costs money.
            return f"{field} is not finite ({value})"
    return ""


def build_shortlist(
    population: Sequence[SymbolStats],
    *,
    as_of: date,
    n: int = CAPTURE_SHORTLIST_N,
) -> Shortlist:
    """The ``n`` most liquid admissible symbols in one day's cross-section.

    ``n`` is a MAXIMUM. Fewer qualify when fewer were measured, and padding would put a symbol
    nobody measured into a campaign that then spends calls on it -- the same rule as `top_n`.

    ``as_of`` is required and has no default. The shortlist decides which symbols have data at
    all, so everything researched on that data inherits its selection; choosing it from a
    cross-section drawn AFTER the capture window would contaminate every result downstream. It
    is recorded rather than verified -- the stats carry no date to check it against -- so it
    documents provenance and does not enforce it.
    """
    rejected = {stat.symbol: reason for stat in population if (reason := _unmeasurable(stat))}
    admissible = [stat for stat in population if stat.symbol not in rejected]

    # A single symbol scores nothing: `liquidity_scores` returns an empty mapping because there
    # is no cross-section to be liquid RELATIVE TO. That leaves it admissible and unselected,
    # which `outranked` reports rather than quietly shipping a one-name shortlist.
    scores = liquidity_scores(admissible)
    ranked = sorted(scores, key=lambda symbol: (-scores[symbol], symbol))

    return Shortlist(
        symbols=tuple(ranked[:n]),
        rejected=rejected,
        n_admissible=len(admissible),
        as_of=as_of,
    )
