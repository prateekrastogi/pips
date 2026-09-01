# pips — NSE cash-equity intraday meta-algorithm
Research factory (Python) certifies signed StrategyBundles; Rust plant executes them under an
independent risk layer. Breeze = read-only data plane; broker adapter = only order plane.
DRY_RUN by default; launch unlevered; no generative AI in the trading loop.

Environment: everything runs as Docker Compose services on arb-vm (SSH); ALL market data and
runtime state live on VM volumes — laptop = code + fixtures only. CI is LOCAL JENKINS (root
Jenkinsfile running the containerized `make ci`), not GitHub Actions. **JENKINS IS A PRE-PUSH
GATE, not just pre-merge**: commit and push often, and every push runs `pips-ci` on the branch
first (`make install-hooks`; `--no-verify` is the loud, logged bypass). A local `make ci` says
"it works here"; the Jenkins green says "it works from what you actually pushed" — that
difference has already caught two clean-checkout failures. Merge to main only on green;
arb-vm's deploy rail auto-builds and runs every new main SHA (trading-path services never
restart during market hours). Verify inside the container with `make ci-container`: it builds
the image FROM the working tree and the image refuses the ladder unless it matches. A raw
`docker compose run` resolves a floating tag and has reported `ci: green` from a day-old build.

LOAD ORDER (strict, to protect context): docs/INDEX.md → docs/state/CURRENT.md → the active
milestone section of IMPLEMENTATION.md → its ledger rows. Everything else on demand only.
Reference docs in docs/reference/ are consulted by section, never ingested.

Commands (Make targets): make setup · test · lint · typecheck · ci · ci-container · provenance ·
determinism · tdd-check · s1-search · s5-smoke · s5-smoke-wide ·
ledger-check · s1-smoke · backtest-smoke · parity DAY=<day> · qc

Constitution (full text IMPLEMENTATION.md §2): TEST-FIRST — every behavioural change starts
as a failing test (red→green→refactor); never write production code before its test, record
the red output in the session log + PR body (rule 16 / §7.1; `make tdd-check` enforces it,
`TDD-Exempt: <reason>` is the only, loud, bypass); determinism; causality = F_t-measurability
(AsOf view; bars close-labeled; no full-day fields intraday; no smoothed states); bitemporal
append-only evidence; every viewed trial counts; falsifiers before search; costs are
effective-dated data; two planes/two credentials/two processes; ≤5 orders/s governor;
../past is a READ-ONLY harvest source — check ledger/salvage.yaml before writing any
connector/adapter/glue (vendor or port donors; from-scratch needs a NONE_FOUND row); donors
often live in commit history rather than HEAD — sweep all branches/tags/deleted files and
extract with `git show <sha>:<path>`, recording the source SHA;
never weaken tests/goldens/gates/ledger to go green; update docs/state/CURRENT.md before
ending every session. BLOCKED? Don't grind: write docs/state/blocks/BLK-####.md and spawn a
FRESH agent with a role synthesized for that blocker's domain (Jenkins / compose / arb-vm /
deploy rail / broker onboarding …) per IMPLEMENTATION.md §10.4 — specialist, never generic.
