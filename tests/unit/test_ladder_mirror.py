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


def test_the_gate_diffs_against_the_pushed_from_sha_not_its_own_origin_main() -> None:
    # In the Jenkins clone origin/main is the gated commit itself, so `BASE=origin/main` is an
    # empty range: tdd-check reported "no commits ahead" and sweep "nothing to sweep" on #321.
    jenkins = (REPO / "Jenkinsfile").read_text(encoding="utf-8")
    for step in ("tdd-check", "sweep"):
        line = next(ln for ln in jenkins.splitlines() if f"make {step}" in ln and '"$IMAGE"' in ln)
        # the shell default keeps a manual build (no parameter) meaningful; the hook always sets it
        assert "BASE=${PIPS_BASE:-origin/main}" in line, line
        assert "BASE=origin/main" not in line
    casc = (REPO / "ops" / "jenkins" / "casc.yaml").read_text(encoding="utf-8")
    assert "stringParam('PIPS_BASE'" in casc
    trigger = (REPO / "ops" / "jenkins" / "trigger.sh").read_text(encoding="utf-8")
    assert "PIPS_BASE" in trigger
