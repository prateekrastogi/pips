"""The dispatcher, its help text and the Makefile agree on what commands exist.

`pips.cli` was the only module under `python/pips/` that no test imported. It is a thin
if-chain, which is why it looked safe -- but three things name commands independently and
nothing held them together:

* the dispatcher, which routes them,
* `_USAGE`, which is what `pips --help` tells a person exists,
* the Makefile, which is the interface CLAUDE.md documents.

They had drifted. `provenance`, `s1-search` and `s5-smoke` were routed and invoked by `make`,
and absent from the help text -- `provenance` being a rung of `make ci`. A command missing from
the help does not exist for anyone who has not read the Makefile or the source, and the help
text is a claim about the tool that was simply wrong.

The commands are compared by parsing the source rather than by introspecting a registry,
because there is no registry: the dispatcher is an if-chain, and building one to make this test
prettier would be a larger change than the finding warrants. Running each command to see
whether it is routed is not an option either -- that is what `backfill` and `qc` do.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "python" / "pips" / "cli.py"
MAKEFILE = ROOT / "Makefile"


def routed() -> set[str]:
    return set(re.findall(r'command == "([a-z0-9-]+)"', CLI.read_text(encoding="utf-8")))


def advertised() -> set[str]:
    """Command names from the help text.

    A command entry has EXACTLY two leading spaces; a wrapped description has more. Keying on
    the indent rather than on "starts with two spaces" is what stops a continuation line being
    read as a command -- my first version picked up `successive` from the wrapped `s1-search`
    entry and reported it as advertised-but-unrouted.
    """
    body = CLI.read_text(encoding="utf-8").split('_USAGE = """')[1].split('"""')[0]
    return {
        line.split()[0]
        for line in body.splitlines()
        if line.strip() and len(line) - len(line.lstrip()) == 2
    }


def make_invoked() -> set[str]:
    return set(re.findall(r"-m pips\.cli ([a-z0-9-]+)", MAKEFILE.read_text(encoding="utf-8")))


def test_the_parsers_find_something() -> None:
    """Three regexes, and a regex that matches nothing makes every comparison below vacuous --
    two empty sets are equal."""
    assert len(routed()) >= 10
    assert len(advertised()) >= 10
    assert len(make_invoked()) >= 10


def test_every_routed_command_is_advertised() -> None:
    """A command absent from `--help` does not exist for anyone who has not read the source.

    This is the direction that had drifted: `provenance`, `s1-search` and `s5-smoke` were all
    routed, all invoked by `make`, and none of them listed -- and `provenance` is a rung of
    `make ci`.
    """
    missing = routed() - advertised()
    assert missing == set(), f"{sorted(missing)} are routed but not in the help text"


def test_every_advertised_command_is_routed() -> None:
    """The other direction, which fails worse: the help text would promise a command that falls
    through to `unknown command` and exit 2, so the tool contradicts itself in one session."""
    phantom = advertised() - routed()
    assert phantom == set(), f"{sorted(phantom)} are advertised but not routed"


def test_every_command_the_makefile_invokes_is_routed() -> None:
    """The Makefile is the interface CLAUDE.md documents. A target invoking a command the
    dispatcher does not know fails only when somebody runs that target -- which, for the ones
    outside `make ci`, could be a long time after the rename that broke it."""
    unrouted = make_invoked() - routed()
    assert unrouted == set(), (
        f"make invokes {sorted(unrouted)}, which the dispatcher does not route"
    )


def test_an_unknown_command_fails_loudly(capsys: pytest.CaptureFixture[str]) -> None:
    """Exit 2 and a message on STDERR, not a quiet zero.

    A dispatcher that returned 0 for a name it did not recognise would let a typo'd Make target
    report success, which is this project's recurring defect wearing a shell.
    """
    from pips.cli import main

    assert main(["definitely-not-a-command"]) == 2
    assert "unknown command" in capsys.readouterr().err


def test_help_exits_zero_and_a_bare_invocation_does_not(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Asking for help succeeded; being given no command at all did not. The two print the same
    text and must not share an exit code -- a script that forgot its argument would otherwise
    look like a script that asked for help."""
    from pips.cli import main

    assert main(["--help"]) == 0
    assert "usage: pips" in capsys.readouterr().out

    assert main([]) == 1
