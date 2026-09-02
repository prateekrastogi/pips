"""M20's Verify, made runnable: how far the factory is from certifying anything.

`[C-SMOKE-01]`. Every other milestone's *Verify* has a Make target — `s1-smoke`, `s5-smoke`,
`backtest-smoke`. M20's did not, so "the chain works and is blocked on one threshold" was a claim
in a session log rather than something anyone could run and see.

The honest difficulty is that a §12.2 dossier wants things the factory does not yet produce:
kill thresholds, flatten deadlines, minimum economic ticket, participation. The tempting smoke
run fills those with `"smoke"` and reports a certified bundle — a lie with a signature on it,
and precisely the failure `[C-WRIT-01]` was written to refuse.

So this supplies **only what the run genuinely knows**: the commit it was built from, the
snapshot root it read, the trial counts the registry recorded, the cost model and venue the
search ran under. Everything else comes back as unsupplied, and the report is a map of what is
actually missing. While the answer is zero certified, that map is the useful artifact — it says
what to build or decide next, with evidence rather than recollection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pips.search.s5 import S5Result

__all__ = ["KNOWN_FIELDS", "RUN_FIELDS", "evidence_from_run", "format_gap", "main"]

KNOWN_FIELDS: tuple[str, ...] = (
    "identity.code_version",
    "identity.data_version",
    "identity.cost_version",
    "trade_context.broker",
    "trade_context.capital_range",
    "stability.trials_viewed",
    "stability.m_erank",
)
"""The claim this module makes: exactly these come from a real run, and nothing else does.

Deliberately short. `identity.strategy_id` and `identity.family_graph` are the nominee's, the
gates are derived from measured metrics (`[C-WRIT-01]`), and `decision.correlation_cluster` is
S5's (`[C-NOM-01]`) — none of them belong to the caller. Everything absent from this tuple is
absent because the factory does not produce it yet, not because nobody got round to mapping it.
"""


RUN_FIELDS: tuple[str, ...] = (
    "snapshot_name",
    "snapshot_root",
    "cost_model",
    "broker",
    "capital_tier",
    "trials_viewed",
    "multiplicity_effective",
)
"""Every key `evidence_from_run` reads. Kept equal to what it reads by a test — a check that
covers five of seven keys refuses some gaps and lets the rest through as a bare `KeyError`."""


def evidence_from_run(report: Mapping[str, Any], *, code_version: str) -> dict[str, Any]:
    """Caller-side evidence for one certification run. Refuses rather than guessing.

    ``report`` is the mapping `run_family_searches` returns. A missing key raises `KeyError`
    rather than defaulting: a run that cannot say which snapshot it read cannot describe itself,
    and a dossier recording a guess is worse than one recording a gap.
    """
    if not code_version.strip():
        raise ValueError(
            "code_version is empty: a dossier whose commit is a guess cannot be checked against "
            "the repository, which is the only thing that makes `identity` evidence at all."
        )
    # Every key this function reads, checked together. A bare `report[key]` would already
    # raise -- but on the FIRST one, with no explanation, so a caller with three gaps learns
    # them one run at a time. The list must stay equal to what is read below, and a test holds
    # it there.
    missing = sorted(key for key in RUN_FIELDS if key not in report)
    if missing:
        raise KeyError(
            f"the run report has no {missing}, so this run cannot describe what it read or ran "
            "under. Refused rather than defaulted: a dossier recording a guess is worse than "
            "one recording a gap."
        )
    return {
        "identity.code_version": code_version,
        "identity.data_version": f"{report['snapshot_name']}@{report['snapshot_root']}",
        "identity.cost_version": report["cost_model"],
        "trade_context.broker": report["broker"],
        "trade_context.capital_range": report["capital_tier"],
        # Rule 4's numbers, and the two a dossier cannot fake: understating either RAISES the
        # DSR that gets reported beside them (§3.6).
        "stability.trials_viewed": report["trials_viewed"],
        "stability.m_erank": report["multiplicity_effective"],
    }


def format_gap(unsupplied: Mapping[str, tuple[str, ...]], *, certified: int) -> list[str]:
    """The verdict first, then what stands in its way.

    The count leads because a report that prints only gaps reads as a warning, and this is a
    result: `0 certified` is the expected output of an honest cycle that is not ready.
    """
    lines = [f"certify-smoke: {certified} certified"]
    for strategy_id in sorted(unsupplied):
        paths = unsupplied[strategy_id]
        lines.append(f"  {strategy_id}: {len(paths)} dossier field(s) the factory cannot supply")
        lines.extend(f"    - {path}" for path in paths)
    return lines


def main(argv: list[str] | None = None) -> int:
    """``pips certify-smoke <fixtures> <registry.db>`` — run the chain and report the distance."""
    import subprocess
    import sys
    from pathlib import Path

    from pips.certification.nominate import nominate
    from pips.certification.run import run_certification
    from pips.data.lockbox import SealedLockbox
    from pips.search.families import run_family_searches
    from pips.search.registry import Registry

    args = list(argv if argv is not None else sys.argv[1:])
    fixtures = Path(args[0]) if args else Path("fixtures")
    db = Path(args[1]) if len(args) > 1 else Path("build/certify-smoke/registry.db")
    db.parent.mkdir(parents=True, exist_ok=True)

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    if not sha:
        print("certify-smoke FAILED: cannot resolve HEAD, so nothing can name its code version")
        return 1

    registry = Registry(db)
    try:
        report = run_family_searches(
            fixtures=fixtures, registry=registry, returns_dir=db.parent / "returns"
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"certify-smoke FAILED: {exc}")
        return 1

    evidence = evidence_from_run(report, code_version=sha)
    nomination = nominate(
        s5=cast("S5Result", report["s5"]),
        evidence_for=lambda _: evidence,
        provenance_for=lambda strategy_id: {"strategy_id": strategy_id},
        alpha_ir_for=lambda _: (),
        portfolio_ir_for=lambda _: (),
    )

    from datetime import date

    result = run_certification(
        nominees=nomination.nominees,
        registry=registry,
        lockbox=SealedLockbox(
            start=date(2026, 7, 1),
            end=date(2026, 8, 1),
            release_stage="S6",
            cycle_id="certify-smoke",
        ),
        stage="S6",
        evaluate_holdout=lambda start, end, ids: dict.fromkeys(ids, 0.0),
        key=b"certify-smoke-not-a-real-key",
    )

    for line in format_gap(nomination.unsupplied, certified=len(result.certification.certified)):
        print(line)
    print(f"  holdout opened: {result.lockbox is not None}")
    for rejection in result.not_finalists:
        print(f"  {rejection.strategy_id} did not reach the holdout:")
        for reason in rejection.reasons:
            print(f"    - {reason.splitlines()[0]}")
    for note in nomination.refused:
        print(f"  refused: {note}")

    print(
        "\n  WHAT THIS IS NOT: a certification. Zero is the expected result while\n"
        "  stability.concentration has no declared bar (ADR-0014) and while the fields listed\n"
        "  above come from nowhere real. Filling them with plausible strings would produce a\n"
        "  signed bundle backed by invented evidence, which is the one outcome worse than none."
    )
    return 0
