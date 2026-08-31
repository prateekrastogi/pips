# ADR-0012 · Breeze quota: 100,000 calls/day, 32 parallel fetches

**Status:** accepted · **Date:** 2026-08-31 · **Supersedes the planning figures in** §6 M3/M4

## Context
IMPLEMENTATION.md was written against conflicting public figures — 100/min versus 75/min —
and a planning assumption of **≤4,500 calls/day**. M3 exists partly to measure the real ones.
The owner has since confirmed the actual entitlement: **100,000 calls per day and 32 parallel
fetches.**

That is a factor of ~22 more daily budget than the plan assumed, and it changes the shape of
the M4 backfill campaign rather than just its speed.

## Decision
Record the two confirmed limits as data (`config/breeze.yaml`, with `source` and
`verified_on` like any effective-dated schedule, rule 6) and re-plan M4 against them:

- **Daily budget: 100,000 calls.** The 1-minute priority campaign (U100/U150/U300 over 3y)
  was estimated at 28k–85k calls, which the plan spread over 6–17 quota-days. It now fits
  inside a single day's budget, so the backfill is bounded by wall-clock and politeness
  rather than by quota.
- **Parallelism: 32 fetches.** The fetcher may run a bounded worker pool at that width. It
  must stay a *configured* value read from `config/breeze.yaml`, not a constant, for the same
  reason square-off times are data (§3.4): an entitlement that changed once will change again.

**The per-minute rate is still UNCONFIRMED**, and is deliberately not inferred from the other
two. 100k/day averages ~70/minute over a 24-hour period, but a daily cap says nothing about
the instantaneous rate a burst of 32 parallel fetches is allowed to reach. Until the M3 probe
measures it, the fetcher keeps a conservative per-minute throttle. Being throttled costs
minutes; being rate-limited mid-campaign costs a resumable-state bug hunt.

## Consequences
- The M4 "resumable budgeter" is still required. A 100k budget removes the multi-day campaign,
  not the need to resume: a fetch interrupted at call 60,000 must not restart at zero.
- SAL-0003's warning is now partially resolved. The `intraday` donor encodes 100/min; that
  constant still must not be inherited — the numbers come from `config/breeze.yaml`, and the
  donor supplies the Status-5 detection and budgeter shape only.
- The M3 probe's remaining job on this axis is narrower: measure the sustained and burst
  per-minute rate, and confirm the daily counter's reset boundary.

## Alternatives
- **Keep the conservative 75/min, 4,500/day planning figures:** would leave M4 planning a
  17-day campaign that has no reason to exist.
- **Infer a per-minute rate from 100k/day:** arithmetic, not evidence. Rejected — the same
  reason the plan refused to pick between 100/min and 75/min without measuring.
