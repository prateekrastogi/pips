# Runbook — Breeze historical backfill

**Runs on arb-vm. Never on a laptop.** Rule 14 puts all market data on VM volumes, and SAL-0001
adds the operational reason: only API *calls* must egress from the whitelisted IP. The browser
login in step 1 can happen anywhere; everything after it cannot.

## 1. Refresh the session token (daily, human)

The Breeze session token expires at midnight. Log in at
`https://api.icicidirect.com/apiuser/login?api_key=<the key in .env>`, copy the `API_Session`
value from the redirect (DevTools → Network → Form Data), and follow
`ops/runbooks/breeze-token.md` to commit it. The deploy rail carries it to the VM within one
poll.

**It is 8 characters.** The first token we tried was 7 and failed with "check session key" —
see `docs/reports/feasibility/breeze-credential-probe.md`.

## 2. Confirm the quota the campaign will spend against

`config/breeze.yaml` holds it as data, not as constants: **100,000 calls/day and 32 parallel
fetches** (ADR-0012, owner-confirmed). The per-minute rate is still **unverified** and sits at
a conservative 75, so pacing is 0.8 s/call. The budgeter applies a further 10% headroom,
because SAL-0003 records real enforcement biting earlier than the published figure — a user hit
the daily error at ~170 calls.

## 3. Run the campaign

```bash
ssh arb-vm
cd /srv/pips/checkout

# Always cost the plan first. It opens no session and spends nothing.
docker compose run --rm --no-deps research python -m pips.cli backfill \
  --symbols RELIND,ICIBAN --from 2026-08-26 --to 2026-08-28 --dry-run

# Then run it.
docker compose run --rm --no-deps research python -m pips.cli backfill \
  --symbols RELIND,ICIBAN --from 2026-08-26 --to 2026-08-28
```

`docker compose run` resolves `pips/research:current`, which the deploy rail republishes after
every successful deploy. If you ever need a specific build, set `PIPS_SHA=<sha>` — but check
`docker images pips/research` first, because an image tag that nobody refreshes is how you end
up running last hour's code against this hour's data.

Writes to `/srv/pips/bronze/<symbol>/<date>/<received_at_ns>.json` — the exact payload, the
receive timestamp, and the request that produced it (§3.4). Append-only: a second observation
of the same window is a new record, never an edit.

## 4. Read the outcome

The run reports `attempted / fetched / empty / errored / skipped` and why it stopped.

| it stopped because | what to do |
|---|---|
| nothing left | done — the manifest has every key |
| **budget spent** | nothing. Resume tomorrow; finished keys cost zero calls |
| **rate limited** | stop and think. The vendor rejected us *below* the configured pace, so the pace is wrong — lower `max_calls_per_minute` in `config/breeze.yaml` rather than retrying |
| errors | inspect. Errored keys are deliberately not marked done and retry on the next run |

## 5. Promote the daily panel (after a `1day` campaign)

The seed's `1day` records are RANGE records and belong in the daily panel beside silver, not in
silver itself (BLK-0003). Promotion spends nothing and opens no session:

```bash
docker compose run --rm --no-deps research python -m pips.cli daily promote /srv/pips \
  --known-on 2026-09-05   # today's date: the as-of for instrument resolution, never defaulted
```

It writes `/srv/pips/daily/bars_1d.parquet` and prints `N of M range record(s) -> R row(s)`.
"no bronze" and "found no range records" both exit 0 and both say **not a pass** — an empty
panel is a campaign that did not run, not a clean one. Exit 2 means no instrument master at
`/srv/pips/pit`. This panel is what `pips.universe.daily_stats` reads for the capture pre-rank.

## 6. Rank the capture shortlist from the daily panel

```bash
docker compose run --rm --no-deps research python -m pips.cli universe prerank /srv/pips \
  --as-of 2026-09-03   # the LAST SESSION IN THE PANEL, not today: check max(trade_date) first
```

Writes `/srv/pips/universes/prerank-<as_of>.json` once; a second run for the same as-of is exit 1
and changes nothing (append-only — look at why the selection would differ, do not replace it).
`--n` defaults to the shortlist width (500) and is a maximum. `--explore K` adds K names from
below the cut on a weekly rotation (default 0). Point the capture at it with `pips capture /srv/pips --shortlist
/srv/pips/universes/prerank-<as_of>.json` (PLAN by default; `--live` to subscribe). Any symbol
that does not resolve to a Breeze code as of the artifact's date refuses the whole run and is
named — fix the master, do not trim the list.

## 7. Daily refresh: yesterday's bars → panel → today's 500 (measured 2026-09-06)

Run after the close, on arb-vm, with the day's token in the checkout's `.env`. Spends ~3,100 calls
at the learned pace; everything else is local compute.

```bash
cd /srv/pips/checkout
D=2026-09-04   # the session just closed
SYMS=$(ls -d /srv/pips/bronze/*/1day | awk -F/ '{print $(NF-1)}' | paste -sd,)   # the seed's codes

# 1. one RANGE record per symbol for the day (~4 min; re-run the same line if it stops rate-limited)
docker compose run --rm --no-deps research python -m pips.cli backfill \
  --symbols "$SYMS" --from $D --to $D --interval 1day --ranged

# 2. the panel, one row per instrument-day (30 min on the old store; time it on the new one)
docker compose run --rm --no-deps research python -m pips.cli daily promote /srv/pips --known-on $(date +%F)

# 3. the shortlist as of that session (88 s), append-only: a second run for the same day refuses
docker compose run --rm --no-deps research python -m pips.cli universe prerank /srv/pips --as-of $D

# 4. resolve it to Breeze codes without opening anything
docker compose run --rm --no-deps research python -m pips.cli capture /srv/pips \
  --shortlist /srv/pips/universes/prerank-$D.json
```

What "done" looks like: step 1 prints `campaign complete`; step 2 prints `N of M range record(s) ->
R row(s)` and a superseded count (the seed's double fetch makes that 1,577,851 — it is not new);
step 3 prints `500 selected of ~2,480 admissible`; step 4 prints `capture: 500 symbol(s): …` and
`planned only, nothing opened`. An empty reply for a name that had bars yesterday is a delisting or
a suspension, quarantined with its reason — look before assuming the vendor failed.

Known clutter: `docker compose` warns about orphan containers `pips-seed-daily` and
`pips-capture-20260904`; the latter's logs are preserved at
`/srv/pips/state/blk-0004-capture-20260904.docker-log`. Remove them when BLK-0004 is closed.

## What the manifest does and does not mean

`/srv/pips/state/backfill-manifest.json` records an **outcome** per key, not just "done":

- `OK` — data returned and written.
- `EMPTY` — attempted, and there is genuinely nothing. A holiday. This is an answer, so it is
  marked done; re-fetching it every run would burn budget on days that will never have data.
- *absent* — not finished. Either never attempted, or attempted and errored, or attempted and
  rate-limited.

**A rate-limited window is never marked done**, and that is the single most important property
here. Breeze returns a rejection as HTTP 200 with `Status: 5` in the body, so a naive client
records it as "no data". Marked done, it becomes a permanent hole in the archive that looks
exactly like a holiday — and unlike a crash, it leaves nothing behind to notice.

## Resuming

Just run it again. Finished keys are skipped without a call, so a resumed campaign costs only
the work that remains. The budgeter's own state (`/srv/pips/state/budget.json`) is keyed by
date, so a new day starts with a full budget while the manifest keeps everything already done.

If the budget state file is ever unreadable, the budgeter assumes the day's quota is **spent**
rather than fresh. Not knowing what we spent must not licence spending it again.
