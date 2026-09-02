# Mutation harness

A quality signal the test ladder does not give: `make ci` says the tests pass, this says whether
they would notice if the code were wrong. Break one thing on purpose, run the tests, and record
whether anything failed. A mutation that survives is a property nothing checks.

    uv run python ops/mutate/mutate.py <spec.json>

    {"source": "python/pips/x.py", "tests": ["tests/unit/test_x.py"], "timeout": 90,
     "mutations": [{"name": "...", "old": "<exact text>", "new": "<replacement>"}]}

Outside `make ci` deliberately: it is a tool for deciding what to test next, not a gate. It is
kept to the same lint and format standard as the rest of the tree even though the ladder does
not check `ops/`.

## What it refuses to get wrong

Every guard here replaced a failure this harness actually had.

**The anchor must be unique.** `str.replace(old, new, 1)` silently mutated the first of several
identical anchors, so two mutations were scored against code the tests never ran.

**Classify on the exit code, never on output text.** `case $OUT in *failed*)` never matched
pytest's uppercase `FAILED`, and six kills were reported as survivals.

**Crash recovery.** `finally` does not survive SIGKILL. A killed run once left a mutation in the
working tree, passed the suite that had run *before* it, and got committed — Jenkins caught it,
nothing local did. The pristine text is written to disk before anything is mutated and a
leftover copy is restored on the next run rather than assumed absent.

**A canary proves the tests exercise the source.** Twice a sweep ran against the wrong test file
and reported every mutant as surviving, which reads exactly like a discovery: *"the weights can
be flipped with no test noticing"*, *"the content hash is not checked"*. Both false, both
alarming enough to be believed. So a module-level `raise` runs first: if the suite still passes,
the tests do not touch that file and the run is refused.

**Stray market data is named.** Mutating a safety guard makes the unsafe thing happen — deleting
rule 14's repo-path check let a backfill write bronze into `./data` for real. The harness
restores the source; it cannot restore the filesystem, so it checks the four data zones after
every run.

## Writing a mutation that means something

Mutate the **mechanism**, not a value. Renaming a tag, appending to a ranking, or changing a
constant can all leave the property intact — the mutant then survives for a reason that has
nothing to do with test coverage, and treating it as a gap produces a test for a bug that does
not exist. The mutation has to be the defect a careless edit would actually produce.

Expect **equivalent** mutants, and say which kind: a safety net for a plausible future change
(`_TERMINAL` in the backfill, kept); provably dead code (`low > high` in `check_bar_sanity` and
both clamps in `robust_level`, removed with the proof); or dead at runtime but load-bearing for
another gate in the ladder (`or score is None` in `certify`, which is what narrows the type for
mypy).
