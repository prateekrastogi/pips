# Runbook — GATE-0: Breeze data-use authority `[G-AUTH-0]`

**Owner: human. The autonomous loop cannot file this, answer it, or clear it.** It is one of
the three human-only pause points in IMPLEMENTATION.md §10.6.

## Why this gate exists

pips reads market data from ICICI Breeze and places orders through a **different** broker.
That split is the architecture (rule 7: two planes, two credentials, two processes), and it is
also the thing ICICI has not published a position on. Their public terms describe Breeze as
being for the customer's own trading and prohibit third-party trading integration; they
explicitly support customers building their own code. What they do not publish is an explicit
statement about the case in the middle — **using Breeze purely as a read-only data source for
signals that the same customer then executes at another broker, on their own account.**

We are not asking permission to do something unusual with the data. We are asking them to
confirm, in writing, that a reading we believe is correct *is* correct — before any real money
depends on it. `[G-AUTH-0]` blocks the live-flag chain until they answer or the feed moves.

**Send it early.** Nothing before P6 is blocked by this, but a written response from a bank's
compliance or API-support function has a long lead time, and the cost of asking is one email.

## The answer we need

One of three outcomes. Each has a defined consequence — none of them is "proceed anyway":

| Outcome | Meaning | What happens |
|---|---|---|
| **Permitted** | Data-only Breeze use with execution elsewhere is fine | Record `GRANTED`; gate clears; Breeze stays the certified signal feed |
| **Not permitted** | They decline, or restrict it | Record `DENIED`; the certified signal feed moves to Flattrade's entitled feed (ADR-0006) — an adapter swap, not an architecture change |
| **No clear answer** | Non-committal, or no reply after chasing | Stays `FILED_AWAITING_RESPONSE`. Treat as not permitted for live purposes; either keep chasing or take the feed swap. **An ambiguous answer is not a yes.** |

Since ADR-0010 deferred Zerodha, the fallback set has exactly **one** member. If Flattrade's
own terms also do not permit it, this gate can then only be cleared by reopening a second
execution venue. That is a real corner, and it is why the question is worth sending early.

## How to send it

Use the official Breeze API support channel from the ICICI Direct / Breeze developer portal —
the API support desk, not a general retail helpline, since this is a terms question about API
usage. **Record which channel you used and the date**, because the record below asks for it.

Do not mix this with technical questions (rate limits, history depth). Those belong in the M3
feasibility probe and diluting a compliance question with them tends to get it answered by the
wrong desk.

## The letter

> **Subject:** Breeze API — clarification on data-only use with execution at another broker
>
> Dear Breeze API Support,
>
> I am an individual ICICI Direct customer with an active Breeze API subscription, and I am
> writing to request written clarification on a permitted-use question before I rely on it.
>
> I am building software, for my own personal use, that reads market data through the Breeze
> API — historical candles and live quotes — and computes trading signals from it. The
> software is entirely self-built and is not offered, sold, or made available to anyone else.
>
> My question concerns where the resulting orders are placed. In my intended setup, orders
> derived from those signals are placed **through a different broker's API, in my own trading
> account at that broker**. Breeze is used **only** as a read-only market-data source: no
> orders are placed through the Breeze API, no Breeze data is redistributed, republished, or
> shared with any third party, and no other person or entity has access to the data or the
> software.
>
> I have read the Breeze API terms and FAQs, which describe the API as being for a customer's
> own trading and prohibit third-party trading integration, and which support customers
> writing their own code. I could not find an explicit statement covering the specific case
> above — read-only data use by the same customer, with execution at another broker.
>
> Could you please confirm in writing whether this use is permitted under the Breeze API
> terms? Specifically:
>
> 1. May I use Breeze market data solely as an input to signals that I execute in my own
>    account at a different broker?
> 2. Are there conditions or limits I should observe for such use?
> 3. If it is not permitted, could you confirm that explicitly, so that I can move my data
>    source accordingly?
>
> I want to be certain I am within the terms before committing to this design, which is why I
> am asking in advance rather than seeking forgiveness afterwards. A written answer, even a
> brief one, is what I need.
>
> Thank you for your time.
>
> Kind regards,
> *(name, ICICI Direct client code, registered email)*

## Recording the response

Update `docs/reports/feasibility/gate0-authority.yaml`. **Editing `status` alone will not
clear the gate** — `python/pips/core/authority.py` refuses to validate a record that claims a
cleared gate without the evidence behind it, and `make ci` runs that check.

On sending:

```yaml
status: FILED_AWAITING_RESPONSE
filed_on: 2026-09-01              # the date you actually sent it
evidence_paths:
  - docs/reports/feasibility/gate0-question-sent.eml    # or .pdf — commit the artifact
notes: "Sent via <the exact channel you used>."
```

On a written answer — save the reply itself into `docs/reports/feasibility/` and commit it,
then:

```yaml
status: GRANTED                   # or DENIED
response_received_on: 2026-09-20
response_summary: "<one factual sentence — what they actually said, not your reading of it>"
evidence_paths:
  - docs/reports/feasibility/gate0-icici-response.pdf
```

If the answer is `DENIED`, the next step is the feed swap: move the certified signal feed to
Flattrade, then set `status: RESOLVED_BY_FEED_SWAP` and `certified_signal_feed: FLATTRADE`.
The record refuses that combination while the feed still says `BREEZE`, because claiming the
swap resolved the gate while nothing swapped is exactly the self-contradiction the gate is
there to catch.

Finally, flip `G-AUTH-0` in `docs/ledger/gates.yaml` to `enforced` and note the outcome in
`docs/state/CURRENT.md`.

## What this gate does not do

It does not, by itself, permit live trading. It is **one** of the three independent parts of
the live-flag chain (rule 8): the engine binary compiled with the `live` feature, `PIPS_LIVE=1`
set by a human on arb-vm, and a config carrying `i_understand_live_trading: true`. All four
conditions — those three plus this gate — must hold. Clearing GATE-0 clears GATE-0.
