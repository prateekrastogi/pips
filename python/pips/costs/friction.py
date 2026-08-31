"""Execution-friction parameters  [C-COST-04] (§3.7, reference §10.2-§10.3).

The statutory stack is exact. These terms are *estimated*, and the reference sets the standard
for how an uncertain constant should be carried: specify the estimator and the refit schedule,
not a number. So this model holds priors, placeholders and the refit schedule together, and
knows whether it has been calibrated.

The conservative direction is asymmetric and the file records it: an overstated cost kills a
live edge and costs opportunity; an understated cost makes a *dead* edge look alive and costs
capital.
"""

from __future__ import annotations

from pathlib import Path

from pips.core.config import DecimalFromStr, PipsConfig, load_yaml

__all__ = ["FrictionParameters", "ImpactParameters", "load_friction"]


class ImpactParameters(PipsConfig):
    """``slippage_bps = kappa * (q / ADV_interval) ** psi``."""

    psi: DecimalFromStr
    psi_source: str
    kappa_bps: DecimalFromStr
    kappa_source: str


class FrictionParameters(PipsConfig):
    """Every non-statutory cost term, with its provenance."""

    schema_version: int
    market: str
    segment: str
    calibrated: bool
    conservative_direction: str
    source: str
    refit_schedule: str
    impact: ImpactParameters
    half_spread_bps: dict[str, DecimalFromStr]
    latency_bps: DecimalFromStr
    latency_source: str
    adverse_selection_bps: DecimalFromStr
    adverse_selection_source: str

    def require_calibrated(self) -> None:
        """Refuse uncalibrated friction on any path to real capital."""
        if not self.calibrated:
            raise RuntimeError(
                "execution friction is not calibrated — kappa, the spread table, latency and "
                "adverse selection are conservative placeholders, not measurements. Calibrate "
                "at M14/M25 before this reaches capital. Research on fixtures may proceed: the "
                "placeholders overstate, so they cannot make a dead edge look alive."
            )


def load_friction(path: Path) -> FrictionParameters:
    """Load and validate the execution-friction parameters."""
    return FrictionParameters.model_validate(load_yaml(path))
