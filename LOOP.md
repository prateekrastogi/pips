# LOOP.md — pips autonomous driver (re-delivered every tick; heartbeat, not a reset)

If you are mid-task in this same session, IGNORE the rest of this file and continue; treat
this delivery as a heartbeat. Otherwise run ONE bounded work unit:

## 0 · Orient (cheapest sufficient read — never more)
- No docs/INDEX.md yet? → BOOTSTRAP: read IMPLEMENTATION.md fully (the only full read,
  ever), then execute M0 and M0.5. Stop after committing.
- Else: read docs/INDEX.md → docs/state/CURRENT.md → the ACTIVE MILESTONE section only of
  IMPLEMENTATION.md → its ledger rows. Do not open reference docs unless the task needs a
  specific section.

## 1 · Pick exactly one action, in this priority order
1. `git status` dirty or verify half-run from a previous tick → finish/commit that first.
2. Open block card escalated to human → check for the human's answer on the card; if none,
   note "waiting on BLK-####" and stop the tick.
3. Open non-escalated block card → act as (or spawn) the §10.4 domain specialist for it.
4. CURRENT.md says awaiting phase gate → if docs/state/gates/P<k>-approved.md exists, open
   the next phase; else re-run the phase's headline Verify (regression watch), update
   CURRENT.md, stop.
5. Otherwise → advance the active milestone (or start the next per §6 order): plan briefly,
   then TDD ONE coherent chunk — write the failing test FIRST, run it, keep the red output;
   write the least code that turns it green; refactor under green. Then run that milestone's
   Verify commands (`docker compose run research make ci` or the milestone-specific target)
   and commit on m/<id>-<slug>.

## 2 · Close the tick (mandatory, even for "nothing to do")
- Overwrite docs/state/CURRENT.md (active item, last verify output, next 3 actions,
  blockers/awaiting). Append one line to docs/state/log/<today>.md — including the RED
  output you observed before the code went green (§7.1 evidence; green-only logs are not TDD).
- Flip any ledger rows you completed. New decision → ADR shard. New block → BLK card.
- Commit. End with a one-line status: DONE <what> | BLOCKED BLK-#### | AWAITING P<k> gate.

## Hard rails (constitution §2 binds every tick)
- Never create/enable anything on the live path: no PIPS_LIVE, no live flags, no real orders.
- Never weaken tests/goldens/gates/ledger to go green. Never touch ../past except read-only.
- Never write production code before a failing test (rule 16). `make tdd-check` refuses the
  branch; a `TDD-Exempt: <reason>` trailer is the only bypass and it must state a real reason.
- Never merge to main with red CI; never proceed past a phase gate without its approved-file.
- Milestone Verify failing after ~3 distinct attempts, or any Jenkins/compose/arb-vm/deploy
  boundary issue → STOP grinding, write the block card, dispatch the specialist (§10.4).
- Human-only items (credentials, spend, broker paperwork, GATE-0 authority, gate sign-offs)
  → record precisely what is needed in CURRENT.md and hold; never simulate or fake them.
- If everything is blocked or awaiting humans: say so in one line and idle — do not invent
  work, do not refactor for sport.
