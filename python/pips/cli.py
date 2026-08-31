"""``pips`` command line -- a thin dispatcher over the research plant's entry points."""

from __future__ import annotations

import sys

__all__ = ["main"]

_USAGE = """usage: pips <command> [args]

commands:
  ledger check [root]        verify the doc/ledger/code/test loop (§8.2)
  tdd check [base] [root]    verify this branch is test-first (§7.1)
  salvage verify [past]      resolve every donor SHA in ../past (§1.2)
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
