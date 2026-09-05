"""`ops/mutate/mutate.py`: a sweep over a RED suite is refused, not reported as 100% killed.

2026-09-05: a chained command edited a test, swept in the same shell, and read "9 killed, 0
survived" -- over a suite that was failing. Every mutant dies for free when the baseline is red,
and the canary (a module-level raise must be noticed) does not catch it. The tool now runs the
listed tests on the UNTOUCHED source first and refuses if they fail.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "ops" / "mutate" / "mutate.py"


def module_and_test(tmp_path: Path, *, test_passes: bool) -> tuple[Path, Path]:
    src = tmp_path / "widget.py"
    src.write_text("def double(x: int) -> int:\n    return x * 2\n", encoding="utf-8")
    expected = 4 if test_passes else 5
    test = tmp_path / "test_widget.py"
    test.write_text(
        "import sys, pathlib\n"
        f"sys.path.insert(0, {str(tmp_path)!r})\n"
        "from widget import double\n\n"
        f"def test_double():\n    assert double(2) == {expected}\n",
        encoding="utf-8",
    )
    return src, test


def spec_for(tmp_path: Path, src: Path, test: Path) -> Path:
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "source": str(src),
                "tests": [str(test)],
                "timeout": 120,
                "mutations": [{"name": "halve", "old": "x * 2", "new": "x // 2"}],
            }
        ),
        encoding="utf-8",
    )
    return spec


def run_tool(spec: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), str(spec)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_a_red_baseline_refuses_the_sweep_and_touches_nothing(tmp_path: Path) -> None:
    src, test = module_and_test(tmp_path, test_passes=False)
    before = src.read_text()
    result = run_tool(spec_for(tmp_path, src, test))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "BASELINE RED" in result.stdout
    assert "KILLED" not in result.stdout and "SURVIVED" not in result.stdout
    assert src.read_text() == before


def test_a_green_baseline_sweeps_and_a_killed_mutant_passes(tmp_path: Path) -> None:
    src, test = module_and_test(tmp_path, test_passes=True)
    result = run_tool(spec_for(tmp_path, src, test))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[halve] KILLED" in result.stdout
    assert src.read_text() == "def double(x: int) -> int:\n    return x * 2\n"


def spec_with_expectation(
    tmp_path: Path, src: Path, test: Path, *, expect: str | None, why: str | None
) -> Path:
    mutation: dict[str, object] = {"name": "noop-rename", "old": "def double", "new": "def double"}
    # an equivalent mutant: renaming nothing changes nothing, so it always survives
    if expect:
        mutation["expect"] = expect
    if why:
        mutation["why"] = why
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {"source": str(src), "tests": [str(test)], "timeout": 120, "mutations": [mutation]}
        )
    )
    return spec


def test_an_unexpected_survivor_fails_the_sweep(tmp_path: Path) -> None:
    src, test = module_and_test(tmp_path, test_passes=True)
    result = run_tool(spec_with_expectation(tmp_path, src, test, expect=None, why=None))
    assert result.returncode == 1
    assert "SURVIVED" in result.stdout


def test_a_declared_equivalent_survivor_with_a_reason_passes(tmp_path: Path) -> None:
    src, test = module_and_test(tmp_path, test_passes=True)
    result = run_tool(
        spec_with_expectation(
            tmp_path, src, test, expect="survive", why="renaming nothing is a no-op"
        )
    )
    assert result.returncode == 0, result.stdout
    assert "EXPECTED" in result.stdout


def test_a_declared_survivor_without_a_reason_is_refused(tmp_path: Path) -> None:
    src, test = module_and_test(tmp_path, test_passes=True)
    result = run_tool(spec_with_expectation(tmp_path, src, test, expect="survive", why=None))
    assert result.returncode == 2
    assert "why" in result.stdout
