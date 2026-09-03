"""``pips`` command line -- a thin dispatcher over the research plant's entry points."""

from __future__ import annotations

import sys

__all__ = ["main"]

_USAGE = """usage: pips <command> [args]

commands:
  ledger check [root]        verify the doc/ledger/code/test loop (§8.2)
  tdd check [base] [root]    verify this branch is test-first (§7.1)
  salvage verify [past]      resolve every donor SHA in ../past (§1.2)
  authority check [record]   report GATE-0 data-use authority [G-AUTH-0]
  deploy guard <service>     may the rail restart this service now? (§2.2)
  provenance                 does this image match the tree it claims? (§2.2)
  s1-smoke [fixtures]        run the S1 funnel end to end on fixtures (§6 M12)
  s1-search <fx> <db> [ret] [silver]
                             successive halving over A01, recording every look (§6 M12)
  s5-smoke [fixtures]        search every family and run S5 across the winners (§6 M15)
  certify-smoke [fixtures]   how far the factory is from certifying (§6 M20)
  backfill --symbols ...     Breeze historical campaign (§6 M4; runs on arb-vm)
  qc [data_root]             quality-check bronze, quarantine failures (§6 M5)
  capture --symbols A,B      PLAN forward capture; --live to subscribe (§6 M4)
  fixtures generate [out]    regenerate the seeded smoke fixtures
  determinism [root]         run the smoke pipeline twice and diff hashes
"""


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in {"-h", "--help"}:
        print(_USAGE)
        return 0 if args else 1

    command, rest = args[0], args[1:]
    if command == "ledger" and rest[:1] == ["check"]:
        from pips.ledger.check import main as ledger_main

        return ledger_main(rest[1:])
    if command == "tdd" and rest[:1] == ["check"]:
        from pips.ledger.tdd import main as tdd_main

        return tdd_main(rest[1:])
    if command == "salvage" and rest[:1] == ["verify"]:
        from pips.ledger.salvage import main as salvage_main

        return salvage_main(rest[1:])
    if command == "authority" and rest[:1] == ["check"]:
        from pips.core.authority import main as authority_main

        return authority_main(rest[1:])
    if command == "provenance":
        from pips.ops.provenance import main as provenance_main

        return provenance_main(rest)
    if command == "deploy" and rest[:1] == ["guard"]:
        from pips.ops.deploy_guard import main as guard_main

        return guard_main(rest[1:])
    if command == "certify-smoke":
        from pips.certification.smoke import main as certify_main

        return certify_main(rest)
    if command == "s5-smoke":
        from pips.search.families import main as families_main

        return families_main(rest)
    if command == "s1-search":
        from pips.search.s1 import search_main

        return search_main(rest)
    if command == "s1-smoke":
        from pips.search.s1 import main as s1_main

        return s1_main(rest)
    if command == "backfill":
        from pips.data.breeze.campaign import main as backfill_main

        return backfill_main(rest)
    if command == "qc":
        from pips.data.qc.runner import main as qc_main

        return qc_main(rest)
    if command == "capture":
        from pips.data.breeze.capture_session import main as capture_main

        return capture_main(rest)
    if command == "fixtures" and rest[:1] == ["generate"]:
        from pips.fixtures.generate import main as fixtures_main

        return fixtures_main(rest[1:])
    if command == "determinism":
        from pips.fixtures.determinism import main as determinism_main

        return determinism_main(rest)

    print(f"unknown command: {' '.join(args)}\n\n{_USAGE}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
