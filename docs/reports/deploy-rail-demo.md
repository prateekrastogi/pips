# Deploy rail — end-to-end demonstration `[G-DEPLOY-01]`

**2026-08-31, on arb-vm.** All three clauses of §6 M3.5's Verify, observed live rather than
argued for. The journal excerpts below are verbatim.

## 1. A main SHA reaches the VM within one poll interval

```
09:57:04  new SHA on origin/main: 481aafeae7e2 -> 05a9ffa5f655
09:57:04  checkout updated; re-executing the new sync.sh before building
09:57:06  re-executed at 05a9ffa5f655; continuing the deploy
09:57:10  built images tagged 05a9ffa5f655
09:57:15  deployed 05a9ffa5f655
```
Push to green Jenkins → merged to main → running on the VM, ~2 minutes, unattended.

## 2. Trading-path services are held during market hours

```
09:57:10  services to promote: breeze-reader research-runner shadow-engine
09:57:12  DEFER breeze-reader (market-hours guard)
            15:27 IST is inside the protected window 08:45-15:35 on a trading day
09:57:13  promoting research-runner   (research/data service, rolls on every main update)
09:57:15  DEFER shadow-engine (market-hours guard)
09:57:15  deployed 05a9ffa5f655; DEFERRED (will retry next poll): breeze-reader shadow-engine
```
§6 asks for this "during **simulated** market hours". It was not simulated — the deploy
happened at 15:27 IST on a trading Monday, so the guard deferred because it genuinely was
market hours. Stronger evidence than the milestone asked for, and free.

## 3. A failing health check rolls back automatically

Failure injected deliberately: `PIPS_EXPECTED_SERVICES="breeze-reader"` while the guard was
already deferring that service, so the health check could not pass.

```
10:01:37  UNHEALTHY breeze-reader: state='absent'
10:01:37  ALERT: health check FAILED at 73af8b8fcdfa; rolling back to 05a9ffa5f655
10:01:48  rollback to 05a9ffa5f655 complete
          checkout SHA afterwards: 05a9ffa
```
The injected variable was removed afterwards. **It also taught something worth keeping:**
`PIPS_EXPECTED_SERVICES` must never name a service the market-hours guard is currently
deferring, or every mid-session deploy will roll itself back. The expectation has to agree
with what the guard permits at the time.

## Four defects this exercise found, none of which reading the code had

Each was found by running the rail, and each was a different bug — not one bug retried.

1. **Partial promotion.** `sync.sh` kept its own service list; compose defined four services
   and the list named six. It promoted `research-runner`, then aborted on `backfill`, leaving
   some services on the new SHA and some on the old — the exact outcome the donor's fourth
   safety property exists to prevent (SAL-0010). Fixed structurally: the rail asks compose
   what exists and the guard how to treat each, so there is no second list to drift.
2. **Self-modification.** `sync.sh` fast-forwards the checkout it runs from, and bash reads a
   script lazily by byte offset. A run began on the old script, pulled in a fix to that same
   script, and continued executing the OLD logic. Now it re-execs after the fast-forward and
   before any build.
3. **The re-exec skipped the deploy.** After re-execing, the checkout is already at the
   target, so the "nothing to do" early exit fired: the rail had fixed the self-modification
   hazard by never deploying at all, and logged a clean "Finished" while doing it. A silent
   no-op reporting success is worse than the loud failure it replaced.
4. **A crash-loop dressed as a service.** `research-runner` runs a command that exits 0 and
   carried `restart: unless-stopped`, so it restarted forever while `docker ps` showed a
   plausible "Restarting". Set to `restart: "no"` until M4 gives it real work — a fake
   long-running command would have been worse, because the health check would then report a
   healthy service that does nothing.

`rollback.sh` carried defect 1 as well, and the test written for it was too narrow to see —
it checked one of the two copies. Both are covered now.
