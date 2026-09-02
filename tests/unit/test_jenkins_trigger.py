"""The Jenkins trigger must not call an unreachable controller a red build  (§2.2, ops).

This bit the session that wrote it. Jenkins restarted while `trigger.sh` was polling, `curl`
returned `(56) Recv failure: Connection reset by peer`, the script exited non-zero, and the
pre-push hook printed **`pips-ci is RED — push blocked`**. The build was fine; the connection
was not.

A gate that FAILED and a gate that COULD NOT RUN need different responses. The first means fix
the code; the second means retry, or check the controller. Reporting one as the other sends the
reader to debug tests that pass — which is the same absence-wearing-the-costume-of-data shape
this project refuses everywhere else, arriving in the tool that enforces it.

Both still block the push. Failing closed is right; only the message and the exit code change.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRIGGER = ROOT / "ops" / "jenkins" / "trigger.sh"

UNREACHABLE = "http://127.0.0.1:1"
"""Port 1 is reserved and nothing listens there, so `curl` fails to connect immediately."""

GATE_DID_NOT_RUN = 3
"""Distinct from 1 (a red build) so the hook can tell them apart. A single non-zero exit is
exactly what made the two indistinguishable."""


def run_trigger() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(TRIGGER), "main"],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "JENKINS_URL": UNREACHABLE, "HOME": "/tmp"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_an_unreachable_controller_is_not_reported_as_a_red_build() -> None:
    result = run_trigger()
    combined = result.stdout + result.stderr

    assert result.returncode == GATE_DID_NOT_RUN, combined
    assert "RED" not in combined, combined


def test_an_unreachable_controller_says_the_gate_did_not_run() -> None:
    """The message has to name the cause, or the reader goes looking for a broken test."""
    result = run_trigger()
    combined = (result.stdout + result.stderr).lower()

    assert "could not reach" in combined or "did not run" in combined, combined


def test_it_still_fails_closed() -> None:
    """Unreachable is not permission to push. Only the diagnosis changes."""
    assert run_trigger().returncode != 0


def test_make_flattens_the_exit_code() -> None:
    """Pinned because it is the trap this whole change exists to avoid.

    `make` exits **2** for any failed recipe, so routing the trigger through `make
    jenkins-build` collapses 3 (could not reach) and 1 (red) into one number. My first version
    of the hook did exactly that, and my first version of THIS test only grepped the hook for
    the constant — proving the number was written down, not that it works.
    """
    result = subprocess.run(
        ["make", "jenkins-build", "REF=main"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "JENKINS_URL": UNREACHABLE, "HOME": "/tmp"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != GATE_DID_NOT_RUN, (
        "make now preserves the recipe's exit code, so the hook could use it after all",
        result.returncode,
    )


def test_the_hook_calls_the_trigger_directly() -> None:
    """Because of the above. Going back through `make` would silently re-flatten the codes."""
    hook = (ROOT / "ops" / "git-hooks" / "pre-push").read_text()
    assert "trigger.sh" in hook
    assert "make jenkins-build" not in hook.replace("`make jenkins-build`", "")


def test_the_hook_branches_on_the_gate_did_not_run_code() -> None:
    hook = (ROOT / "ops" / "git-hooks" / "pre-push").read_text()
    assert str(GATE_DID_NOT_RUN) in hook
    assert "did not run" in hook.lower()


def test_the_hook_reports_did_not_run_end_to_end(tmp_path: Path) -> None:
    """The branch, actually executed rather than grepped for.

    Run in place, the hook says "nothing to build" — HEAD equals its upstream — so the branch
    under test never runs and every in-repo attempt passes vacuously. A scratch repo with a
    commit ahead of its upstream is what makes the hook reach the gate at all.
    """
    remote, work = tmp_path / "remote.git", tmp_path / "work"
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)}

    def run(
        args: list[str], cwd: Path, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )

    run(["git", "init", "-q", "--bare", str(remote)], tmp_path)
    run(["git", "clone", "-q", str(remote), str(work)], tmp_path)
    for relative in ("ops/jenkins/trigger.sh", "ops/git-hooks/pre-push"):
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / relative).read_text())
    run([*git, "add", "-A"], work)
    run([*git, "commit", "-q", "-m", "first"], work)
    run(["git", "push", "-q", "-u", "origin", "HEAD:main"], work)
    (work / "ahead.txt").write_text("ahead\n")
    run([*git, "add", "-A"], work)
    run([*git, "commit", "-q", "-m", "ahead"], work)

    result = run(
        ["bash", "ops/git-hooks/pre-push", "origin"], work, {**env, "JENKINS_URL": UNREACHABLE}
    )
    combined = result.stdout + result.stderr

    assert "nothing to build" not in combined, "the hook never reached the gate"
    assert result.returncode != 0, "unreachable is not permission to push"
    assert "GATE DID NOT RUN" in combined, combined
    assert "is RED" not in combined, combined
