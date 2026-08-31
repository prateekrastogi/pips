# ADR-0003 · Launch unlevered

**Status:** accepted · **Date:** 2026-08-31

## Context
MIS intraday leverage makes a marginal edge look fundable. It also multiplies every
modelling error, and the failure mode is a margin call, not a smaller Sharpe.

## Decision
Go live **unlevered** across the declared tiers (₹2L / ₹5L / ₹10L). Leverage is a later,
separately-validated overlay with its own certification cycle. This supersedes the v1
working assumption of 4×.

## Alternatives
- Launch at broker-max leverage: rejected; rescues weak backtests by construction.
- Modest fixed leverage: still an unvalidated overlay. Deferred, not softened.

## Consequences
Capacity and cost-per-trade economics are evaluated on unlevered notional. Any bundle whose
edge only clears costs under leverage fails the gate rather than earning an exception.
