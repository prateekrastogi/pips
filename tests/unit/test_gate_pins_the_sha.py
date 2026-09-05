"""The pre-push gate must refuse a push if the branch moved while the gate was running.

INCIDENT, 2026-09-05. A gated push started with `main` at e13dc08; the Jenkins gate ran ~15
minutes and built e13dc08 (build #309 console: `git checkout -f e13dc08...`). At 10:00:12Z, mid-
gate, a further commit dd3a55b was made on `main`. GitHub's activity log records ONE push at
10:11:03Z moving `main` 5b57fcb6 -> dd3a55b2. So dd3a55b reached `main` and was deployed without
any Jenkins build ever having seen it.

Two controlled experiments in throwaway repos showed `git push` sending the PRE-hook ref, not a
commit made during the hook -- so the mechanism by which dd3a55b travelled is NOT explained, and
this file does not pretend otherwise. What it does is close the window regardless of mechanism:
the hook records the SHA it is gating and refuses if `HEAD` differs when the gate returns. A
branch that moved during a fifteen-minute gate has, by definition, commits the gate never saw.

The hook is exercised for real: a temp repo with `core.hooksPath` pointing at the repo's own
`ops/git-hooks`, and a stub `ops/jenkins/trigger.sh` standing in for Jenkins.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "ops" / "git-hooks" / "pre-push"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)


def _repo_with_hook(tmp_path: Path, trigger_body: str) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(remote), str(work))
    # The real repository's branch is `main`; a clone defaults to `master`, and bare `git push`
    # refuses when the local name differs from its upstream's. Match reality before committing.
    _git(work, "checkout", "-q", "-b", "main")
    _git(work, "commit", "-q", "--allow-empty", "-m", "base")
    _git(work, "push", "-q", "-u", "origin", "HEAD:main")
    # The real hook, through core.hooksPath exactly as `make install-hooks` sets it up.
    hooks = work / "ops" / "git-hooks"
    hooks.mkdir(parents=True)
    shutil.copy(HOOK, hooks / "pre-push")
    _git(work, "config", "core.hooksPath", "ops/git-hooks")
    # A stub Jenkins trigger: green, but with whatever side effect the test wants.
    trig = work / "ops" / "jenkins" / "trigger.sh"
    trig.parent.mkdir(parents=True)
    trig.write_text("#!/bin/sh\n" + trigger_body + "\nexit 0\n", encoding="utf-8")
    trig.chmod(0o755)
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "hook + stub trigger")
    _git(work, "push", "-q")  # this one is gated by the stub too; it must not move HEAD yet
    return work


def test_a_green_gate_on_an_unmoved_branch_still_pushes(tmp_path: Path) -> None:
    """The control: the guard must not refuse the ordinary case."""
    work = _repo_with_hook(tmp_path, "echo gate-ok")
    _git(work, "commit", "-q", "--allow-empty", "-m", "A")
    a = _git(work, "rev-parse", "HEAD").stdout.strip()
    pushed = _git(work, "push")
    assert pushed.returncode == 0, pushed.stderr
    assert _git(tmp_path / "remote.git", "rev-parse", "main").stdout.strip() == a


def test_a_branch_that_moved_during_the_gate_is_refused(tmp_path: Path) -> None:
    """The incident, reproduced: the gate is green for A, but B appears before it returns."""
    work = _repo_with_hook(
        tmp_path,
        'git -c user.email=t@t -c user.name=t commit -q --allow-empty -m "B during the gate"',
    )
    _git(work, "commit", "-q", "--allow-empty", "-m", "A")
    a = _git(work, "rev-parse", "HEAD").stdout.strip()
    pushed = _git(work, "push")
    assert pushed.returncode != 0, "the branch moved while the gate ran; the push must be refused"
    assert "moved" in pushed.stderr.lower(), pushed.stderr
    # And nothing left the machine: the remote is still where it was before A.
    remote_main = _git(tmp_path / "remote.git", "rev-parse", "main").stdout.strip()
    assert remote_main != a
    assert (
        "B during the gate" not in _git(tmp_path / "remote.git", "log", "--oneline", "main").stdout
    )
