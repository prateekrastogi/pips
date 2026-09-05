"""`ops/mutate/sweep.py`: every changed production module is swept by a committed spec, or the
ladder
is red.

Manual sweeps found the day's best defects and nothing enforced them. `make sweep` takes the
production modules changed against BASE, requires a spec under `ops/mutate/specs/` for each, and
runs the tool. A changed module WITHOUT a spec fails -- the same ratchet `ledger-check` applies to
rows -- and a survivor fails unless the spec declares it `expect: survive` with a `why`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load_sweep() -> Any:
    """ops/mutate is a tool tree, not a package; load it by path so mypy needs no stub."""
    spec = importlib.util.spec_from_file_location("sweep", REPO / "ops" / "mutate" / "sweep.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["sweep"] = module  # dataclasses resolve string annotations via sys.modules
    spec.loader.exec_module(module)
    return module


sweep = _load_sweep()


def write_spec(specs: Path, name: str, source: str) -> Path:
    specs.mkdir(parents=True, exist_ok=True)
    p = specs / f"{name}.json"
    p.write_text(json.dumps({"source": source, "tests": ["tests/unit/x.py"], "mutations": []}))
    return p


def test_changed_production_modules_are_matched_to_specs_and_the_unmatched_are_named(
    tmp_path: Path,
) -> None:
    specs = tmp_path / "specs"
    a = write_spec(specs, "a", "python/pips/a.py")
    plan = sweep.plan(
        changed=[
            "python/pips/a.py",
            "python/pips/b.py",
            "tests/unit/test_a.py",
            "docs/x.md",
            "python/pips/__init__.py",
        ],
        specs_dir=specs,
    )
    assert plan.to_run == [a]
    assert plan.missing == ["python/pips/b.py"]
    assert plan.ignored == ["docs/x.md", "python/pips/__init__.py", "tests/unit/test_a.py"]


def test_nothing_changed_is_a_pass_that_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = sweep.run(changed=[], specs_dir=tmp_path, runner=lambda spec: 0)
    assert rc == 0
    assert "no production module changed" in capsys.readouterr().out


def test_a_missing_spec_is_red_even_if_every_present_spec_is_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    specs = tmp_path / "specs"
    write_spec(specs, "a", "python/pips/a.py")
    rc = sweep.run(
        changed=["python/pips/a.py", "python/pips/b.py"], specs_dir=specs, runner=lambda spec: 0
    )
    assert rc == 1
    assert "python/pips/b.py" in capsys.readouterr().out


def test_a_failing_sweep_is_red_and_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    specs = tmp_path / "specs"
    write_spec(specs, "a", "python/pips/a.py")
    write_spec(specs, "b", "python/pips/b.py")
    rc = sweep.run(
        changed=["python/pips/a.py", "python/pips/b.py"],
        specs_dir=specs,
        runner=lambda spec: 1 if spec.name == "b.json" else 0,
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "b.json" in out and "FAILED" in out


def test_a_spec_that_names_a_source_nobody_changed_is_not_run(tmp_path: Path) -> None:
    specs = tmp_path / "specs"
    write_spec(specs, "z", "python/pips/z.py")
    ran: list[Path] = []

    def record(spec: Path) -> int:
        ran.append(spec)
        return 0

    rc = sweep.run(changed=["python/pips/a.py"], specs_dir=specs, runner=record)
    assert rc == 1  # a.py has no spec
    assert ran == []
