"""`--help` is a request, not an argument.

Every `pips` subcommand parses its own arguments, and the ones doing it by hand read the help
flag as a positional. Measured on 2026-09-04, twelve of fifteen commands did something other
than help when asked for help, and two of them did real work:

    pips fixtures generate --help   ->  "fixtures written to fixtures: 11 files"
    pips determinism --help         ->  ran the smoke pipeline twice
    pips qc --help                  ->  "no bronze at --help/bronze"
    pips ledger check --help        ->  FileNotFoundError: --help/docs/ledger/contracts.yaml

The first is destructive from the repo root: it overwrites the project's own fixtures. Three
more exited **0** while doing nothing, which is this project's oldest defect shape -- a thing
that did not happen reading as a thing that succeeded.

The command list is read out of `_USAGE` rather than restated here, so a new command is covered
the day it is documented.
"""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path

import pytest

from pips.cli import _OWN_HELP, _USAGE, main


def documented_commands() -> list[str]:
    """The command word from each entry in `_USAGE`.

    `s1-search` wraps onto a continuation line indented past the command column, and a parser
    that missed that would read "successive" as a command. Asserted below rather than assumed.
    """
    found = []
    for line in _USAGE.splitlines():
        if line.startswith("  ") and not line[2:3].isspace():
            found.append(line[2:].split()[0])
    return found


def test_the_command_list_parses_the_way_this_file_assumes() -> None:
    """Validate the scan before trusting it -- the wrapped line is the trap."""
    commands = documented_commands()
    assert "s1-search" in commands
    assert "successive" not in commands, "a wrapped continuation was read as a command"
    assert {"qc", "promote", "determinism", "fixtures", "ledger"} <= set(commands)
    assert len(commands) == len(set(commands)), "duplicate command in _USAGE"


@pytest.mark.parametrize("command", documented_commands())
def test_asking_for_help_prints_usage_and_does_nothing_else(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Help must answer, exit 0, and leave the filesystem exactly as it found it."""
    monkeypatch.chdir(tmp_path)
    before = set(os.listdir(tmp_path))
    out, err = io.StringIO(), io.StringIO()
    code: int | None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([command, "--help"])
    except SystemExit as exit_:  # argparse answers by exiting, which is also an answer
        code = int(exit_.code or 0)
    text = (out.getvalue() + err.getvalue()).strip()

    assert code == 0, f"`pips {command} --help` exited {code}: {text[:200]}"
    assert text.lower().startswith("usage"), f"`pips {command} --help` said: {text[:200]}"
    assert set(os.listdir(tmp_path)) == before, (
        f"`pips {command} --help` wrote to the working directory"
    )


@pytest.mark.parametrize("command", sorted(_OWN_HELP))
def test_commands_exempted_from_central_help_really_do_print_their_own(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_OWN_HELP` is an exemption, so it has to be earned every time it is claimed.

    The exemption exists because argparse lists every flag with its metavar, which the one-line
    fallback cannot. A command dropped from argparse would still be waved past the central
    handler and go back to eating the flag -- so the test checks for argparse's own marks
    (`[-h]`), not merely for the word "usage" that both paths produce.
    """
    monkeypatch.chdir(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    with (
        contextlib.suppress(SystemExit),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        main([command, "--help"])
    text = out.getvalue() + err.getvalue()
    assert "[-h]" in text, f"`pips {command}` is exempted from central help but prints none"
    assert command in text


@pytest.mark.parametrize("command", documented_commands())
def test_the_short_flag_is_help_too(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`-h` is the flag people actually type, and it was eaten the same way `--help` was."""
    monkeypatch.chdir(tmp_path)
    before = set(os.listdir(tmp_path))
    out, err = io.StringIO(), io.StringIO()
    code: int | None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([command, "-h"])
    except SystemExit as exit_:
        code = int(exit_.code or 0)
    text = (out.getvalue() + err.getvalue()).strip()
    assert code == 0, f"`pips {command} -h` exited {code}: {text[:200]}"
    assert text.lower().startswith("usage"), f"`pips {command} -h` said: {text[:200]}"
    assert set(os.listdir(tmp_path)) == before, f"`pips {command} -h` wrote to the cwd"


def test_an_unknown_command_is_refused_rather_than_helped() -> None:
    """And the refusal shows the whole usage, not a wrapped continuation line.

    `_usage_for` scans `_USAGE` for the entry naming the command. A scan that accepted any
    indented line would match `s1-search`'s continuation -- so asking for help on a command
    named `successive` would answer with half of another command's description, presented as
    though it were real. The reader has no way to tell that apart from a genuine entry.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["successive", "--help"])
    text = out.getvalue() + err.getvalue()
    # REFUSED, not helped. Exit 0 would report success for a command pips cannot run.
    assert code == 2, f"an unknown command was helped rather than refused: {text[:200]}"
    assert "unknown command" in text
    # The full usage lists every command; a continuation fragment lists none of them.
    assert "qc [data_root]" in text and "promote <root>" in text
