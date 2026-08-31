"""Non-statutory cost terms [C-COST-04] (§3.7, reference §10.2-§10.3).

`cost_rt_bps = statutory + brokerage + spread·aggression + impact κ(q/ADV)^ψ + latency
+ adverse selection`. The statutory half is exact and golden-tested. This half is *estimated*,
and the reference is explicit about what that means: "where a constant's true value is
uncertain, the document specifies the estimator and the refit schedule rather than a number —
that is the intended meaning of 'no voodoo'."

So every parameter here is either a stated prior (ψ ≈ 0.5) or a conservative placeholder that
declares itself unverified. What IS pinned is the structure: the terms are additive, and cost
must rise with aggression and with participation — otherwise the turnover optimiser has no
well-posed interior optimum (§10.2).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from pips.core.calendar import SessionState
from pips.costs.model import CostContext, cost_rt_bps
from pips.costs.schedule import load_cost_schedule
from pips.costs.statutory import Broker

ROOT = Path(__file__).resolve().parents[3]
SCHEDULE = load_cost_schedule(ROOT / "config" / "costs" / "nse_equity_intraday.yaml")
FRICTION = ROOT / "config" / "costs" / "execution_friction.yaml"
DAY = date(2026, 8, 31)


def ctx(**over: object) -> CostContext:
    base: dict[str, object] = {
        "broker": Broker.FLATTRADE,
        "notional_paise": 100_000 * 100,
        "aggression": Decimal("1.0"),
        "participation": Decimal("0.001"),  # q / ADV_interval
        "session": SessionState.MID,
        "trade_date": DAY,
    }
    base.update(over)
    return CostContext(**base)  # type: ignore[arg-type]


# --------------------------------------------------- the structure that is pinned -------


def test_cost_rises_with_aggression() -> None:
    # §10.2: the turnover optimiser "must see costs *rise* with aggression to have a
    # well-posed interior optimum". If this ever stops holding, S5 has no interior solution
    # and will happily choose infinite turnover.
    passive = cost_rt_bps(SCHEDULE, FRICTION, ctx(aggression=Decimal("0.0")))
    mid = cost_rt_bps(SCHEDULE, FRICTION, ctx(aggression=Decimal("0.5")))
    taker = cost_rt_bps(SCHEDULE, FRICTION, ctx(aggression=Decimal("1.0")))
    assert passive.total_bps < mid.total_bps < taker.total_bps


def test_cost_rises_with_participation() -> None:
    small = cost_rt_bps(SCHEDULE, FRICTION, ctx(participation=Decimal("0.001")))
    large = cost_rt_bps(SCHEDULE, FRICTION, ctx(participation=Decimal("0.05")))
    assert large.impact_bps > small.impact_bps


def test_the_decomposition_is_additive_and_complete() -> None:
    # §10.3: IS = half-spread + temporary impact + timing/latency + fees, "additive by
    # construction". A total that is not the sum of its named parts cannot be attributed,
    # and attribution is what tells you which investment fixes execution.
    c = cost_rt_bps(SCHEDULE, FRICTION, ctx())
    parts = c.statutory_bps + c.spread_bps + c.impact_bps + c.latency_bps + c.adverse_selection_bps
    assert c.total_bps == parts


def test_impact_follows_the_square_root_prior() -> None:
    # ψ ≈ 0.5 is the stated prior (§10.2). Quadrupling participation should roughly double
    # the impact term, not quadruple it.
    a = cost_rt_bps(SCHEDULE, FRICTION, ctx(participation=Decimal("0.01"))).impact_bps
    b = cost_rt_bps(SCHEDULE, FRICTION, ctx(participation=Decimal("0.04"))).impact_bps
    ratio = b / a
    assert Decimal("1.9") < ratio < Decimal("2.1"), f"impact scaled by {ratio}, expected ~2"


def test_zero_participation_has_zero_impact() -> None:
    assert cost_rt_bps(SCHEDULE, FRICTION, ctx(participation=Decimal("0"))).impact_bps == 0


def test_the_statutory_component_matches_the_exact_golden() -> None:
    # The one term that is not an estimate must survive composition unchanged.
    c = cost_rt_bps(SCHEDULE, FRICTION, ctx(aggression=Decimal("0")))
    assert c.statutory_bps == Decimal("3.548")


# ------------------------------------------------- session structure --------------------


def test_the_spread_term_is_session_dependent() -> None:
    # §3.7 lists a session-dependent spread table as an M9 deliverable. The open is not the
    # middle of the day, and a single average spread would flatter open-session strategies
    # and penalise mid-session ones.
    shock = cost_rt_bps(SCHEDULE, FRICTION, ctx(session=SessionState.OPEN_SHOCK)).spread_bps
    mid = cost_rt_bps(SCHEDULE, FRICTION, ctx(session=SessionState.MID)).spread_bps
    assert shock > mid


def test_an_untradeable_session_is_refused() -> None:
    # CAS is disabled as an alpha venue (ADR-0004); FLATTEN_ONLY is exposure-reducing only.
    # Quoting a cost for them would imply they are venues we trade.
    for session in (SessionState.CAS, SessionState.FLATTEN_ONLY):
        with pytest.raises(ValueError, match="not a tradeable session"):
            cost_rt_bps(SCHEDULE, FRICTION, ctx(session=session))


# ------------------------------------- unverified parameters must say so ----------------


def test_the_friction_parameters_declare_themselves_unverified() -> None:
    from pips.costs.friction import load_friction

    friction = load_friction(FRICTION)
    assert friction.calibrated is False
    with pytest.raises(RuntimeError, match="not calibrated"):
        friction.require_calibrated()


def test_placeholders_overstate_rather_than_understate() -> None:
    # The conservative direction for a cost model is UP. An understated cost makes a dead
    # edge look alive, which is the single most expensive error this project can make.
    from pips.costs.friction import load_friction

    friction = load_friction(FRICTION)
    assert friction.conservative_direction == "OVERSTATE"
    # A placeholder round trip must clear the statutory floor by a wide margin.
    c = cost_rt_bps(SCHEDULE, FRICTION, ctx())
    assert c.total_bps > c.statutory_bps * 2


def test_stressed_cost_is_at_least_the_unstressed_cost() -> None:
    # M16 stresses costs x1.5 and x2. A "stress" that could come out lower is not a stress.
    base = cost_rt_bps(SCHEDULE, FRICTION, ctx())
    stressed = cost_rt_bps(SCHEDULE, FRICTION, ctx(), stress_multiplier=Decimal("1.5"))
    assert stressed.total_bps >= base.total_bps
    assert stressed.statutory_bps == base.statutory_bps  # statutory is exact, never stressed


# --------------------------- the negative result carried from SAL-0014 ------------------


def test_corwin_schultz_is_absent_from_the_cost_path() -> None:
    """Structural guard ported from SAL-0014's Layer 2.

    The donor did not hand us a spread estimator to use — it handed us a **documented
    negative result**: Corwin-Schultz on aggregated OHLC produced an estimate an order of
    magnitude above their measured anchor, and they built an AST scan to keep it out of the
    cost path permanently. Rediscovering that would have cost real time. A cost-path module
    that references it is a reintroduction, and this test is what notices.
    """
    import ast

    # An AST scan over IDENTIFIERS, not a text search — and the difference is the whole
    # point. The first version of this test grepped raw source and failed on model.py's own
    # docstring, which exists to explain why the estimator is absent. A guard that punishes
    # documenting the exclusion teaches people to delete the explanation. The donor scanned
    # the parsed tree for exactly this reason.
    cost_path = sorted((ROOT / "python" / "pips" / "costs").rglob("*.py"))
    assert cost_path, "cost path is empty — this guard would pass vacuously"
    banned = ("corwin", "schultz", "cs_spread", "high_low_spread")

    def identifiers(tree: ast.AST) -> set[str]:
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                found.add(node.id)
            elif isinstance(node, ast.Attribute):
                found.add(node.attr)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                found.add(node.name)
            elif isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                found.add(node.module or "")
                found.update(a.name for a in node.names)
        return {f.lower() for f in found}

    for module in cost_path:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        names = identifiers(tree)
        for term in banned:
            offenders = [n for n in names if term in n]
            assert not offenders, (
                f"{module.name} references {offenders}. SAL-0014 records Corwin-Schultz "
                "producing an order-of-magnitude-wrong spread on aggregated OHLC; it must "
                "not re-enter the cost path. Use the measured spread table instead."
            )

    # And the guard must be capable of firing: prove it catches a real reintroduction.
    reintroduction = ast.parse(
        "from x import corwin_schultz_spread_bp\nv = corwin_schultz_spread_bp()"
    )
    assert any("corwin" in n for n in identifiers(reintroduction))
