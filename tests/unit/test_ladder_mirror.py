"""The Jenkins gate runs exactly the ladder `make ci` runs -- checked, not trusted.

The Jenkinsfile says its stages "mirror the make ci ladder 1:1". Nothing enforced that, and a
step added to one and not the other is a gate that silently stopped gating.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def ladder_steps() -> list[str]:
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    m = re.search(r"^ci:\s*([^#\n]*)", text, re.M)
    assert m, "no `ci:` target"
    return m.group(1).split()


def jenkins_steps() -> list[str]:
    text = (REPO / "Jenkinsfile").read_text(encoding="utf-8")
    return re.findall(r'"\$IMAGE"\s+make\s+([a-z0-9-]+)', text)


def test_jenkins_runs_every_ladder_step_and_nothing_the_ladder_does_not() -> None:
    assert jenkins_steps() == ladder_steps()


def test_the_sweep_is_a_ladder_step_after_the_tests() -> None:
    steps = ladder_steps()
    assert "sweep" in steps
    assert steps.index("sweep") > steps.index("test")
