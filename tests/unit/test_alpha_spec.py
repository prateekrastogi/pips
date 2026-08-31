"""AlphaSpec and the Forecast contract [C-SPEC-01] [C-FCST-01] (§3.2, §3.3, rule 5).

"No alpha enters as an indicator recipe" (§3.2). It enters as a pre-registration carrying its
mechanism, its null models and — the part that does the work — its **written falsifiers**,
declared *before* the search. Rule 5 says every alpha ships with named null models and a
written rejection condition before it is searched, so a spec missing either must not validate:
the discipline is worthless if it is optional at the point of entry.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from pips.alphas.forecast import Forecast, tradeable
from pips.alphas.spec import AlphaSpec, DataTier, load_alpha_spec

ROOT = Path(__file__).resolve().parents[2]
A01 = ROOT / "config" / "search_spaces" / "A01_residual_momentum.yaml"


def spec_payload(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = dict(load_alpha_spec(A01).model_dump(mode="json"))
    base.update(over)
    return base


# ------------------------------------------------------- the shipped spec ---------------


def test_the_a01_spec_loads() -> None:
    spec = load_alpha_spec(A01)
    assert spec.id == "A01"
    assert spec.data_tier is DataTier.T1
    assert spec.heuristic is False


def test_the_spec_carries_every_field_the_contract_names() -> None:
    # §3.2's tuple A = (H, I_t, T_h, φ_θ, C, E, N, F). A spec missing a leg is not a
    # pre-registration, it is a recipe with extra ceremony.
    declared = {
        "hypothesis",
        "information_set",
        "target",
        "feature_dag",
        "parameter_domain",
        "fit_protocol",
        "null_models",
        "falsifiers",
        "data_tier",
        "cost_context",
        "execution_policy",
        "heuristic",
        "references",
    }
    assert declared <= set(AlphaSpec.model_fields)


# ------------------------------------------------- rule 5 enforced at entry -------------


def test_a_spec_without_falsifiers_is_refused() -> None:
    # "falsifiers before search" (rule 5). Not a warning — a refusal.
    with pytest.raises(ValueError, match="falsifier"):
        AlphaSpec.model_validate(spec_payload(falsifiers=[]))


def test_a_spec_without_null_models_is_refused() -> None:
    with pytest.raises(ValueError, match="null_models"):
        AlphaSpec.model_validate(spec_payload(null_models=[]))


def test_a_falsifier_must_state_a_condition_not_a_sentiment() -> None:
    # "reject if it stops working" is not a rejection condition. A falsifier must name a
    # perturbation and a threshold, or it cannot be evaluated after the fact.
    with pytest.raises(ValueError, match="condition"):
        AlphaSpec.model_validate(spec_payload(falsifiers=["looks bad"]))


def test_a_heuristic_alpha_declares_itself_quarantined() -> None:
    # Rule 5: heuristic: true => quarantined, ensemble cap applies. The flag must be
    # explicit so nothing enters the ensemble by omission.
    spec = AlphaSpec.model_validate(spec_payload(heuristic=True))
    assert spec.quarantined is True
    assert load_alpha_spec(A01).quarantined is False


def test_a_material_change_bumps_the_version_and_is_a_new_trial() -> None:
    # §3.2: "Any material change bumps the version and counts as a new trial." The spec hash
    # is what makes that mechanical rather than a promise.
    base = load_alpha_spec(A01)
    changed = AlphaSpec.model_validate(spec_payload(parameter_domain={"lookback_m": [3, 60]}))
    assert changed.content_hash() != base.content_hash()


def test_a_t2_claim_on_t1_data_is_refused() -> None:
    # §5: microstructure claims are quarantined until the quote/depth archive exists. A spec
    # that declares T2 while its information set is 1-minute OHLCV is claiming data it has
    # not got.
    with pytest.raises(ValueError, match="T2"):
        AlphaSpec.model_validate(spec_payload(data_tier="T2"))


# ------------------------------------------------- the Forecast contract ----------------


def forecast(**over: Any) -> Forecast:
    base: dict[str, Any] = {
        "strategy_id": "A01@1.0.0",
        "family_id": "A01",
        "instrument_id": "SMOKEA",
        "decision_ts": 1_000_000_000,
        "expected_return_bps": Decimal("12.0"),
        "confidence": Decimal("0.6"),
        "horizon_ns": 60 * 1_000_000_000,
        "half_life_ns": 30 * 1_000_000_000,
        "valid_until_ns": 1_060_000_000_000,
        "capacity_notional_paise": 5_000_000,
        "validity_flags": [],
    }
    base.update(over)
    return Forecast.model_validate(base)


def test_a_forecast_carries_comparable_economics() -> None:
    # §3.3: every alpha emits the same economics, independent of order logic — that is what
    # lets the portfolio layer compare A01 against A12 at all.
    f = forecast()
    assert f.expected_return_bps == Decimal("12.0")
    assert f.valid_until_ns > f.decision_ts


def test_a_forecast_that_expires_before_it_is_made_is_refused() -> None:
    with pytest.raises(ValueError, match="valid_until"):
        forecast(valid_until_ns=999)


def test_the_trade_gate_needs_edge_above_stressed_cost_plus_estimation_error() -> None:
    # §3.3: trade only where |mu| > stressed marginal cost + kappa * SE(mu). Both terms
    # matter — clearing cost while inside the estimation error is trading on noise.
    f = forecast(expected_return_bps=Decimal("12.0"))
    assert tradeable(f, stressed_cost_bps=Decimal("8.0"), kappa=Decimal(2), se_bps=Decimal("1.0"))
    assert not tradeable(
        f, stressed_cost_bps=Decimal("11.0"), kappa=Decimal(2), se_bps=Decimal("1.0")
    )
    # Clears the cost by 4bps but the estimate is worth +/- 3bps at kappa=2: not tradeable.
    assert not tradeable(
        f, stressed_cost_bps=Decimal("8.0"), kappa=Decimal(2), se_bps=Decimal("3.0")
    )


def test_the_gate_is_symmetric_in_sign() -> None:
    # A short forecast of -12bps is as tradeable as a long one of +12bps; the gate is on
    # |mu|, not mu.
    short = forecast(expected_return_bps=Decimal("-12.0"))
    assert tradeable(
        short, stressed_cost_bps=Decimal("8.0"), kappa=Decimal(2), se_bps=Decimal("1.0")
    )


def test_a_forecast_flagged_invalid_is_never_tradeable() -> None:
    # validity_flags exist so a forecast can say "do not use me" without the caller having to
    # infer it from the numbers.
    f = forecast(validity_flags=["STALE_FEED"])
    assert not tradeable(f, stressed_cost_bps=Decimal(0), kappa=Decimal(0), se_bps=Decimal(0))
