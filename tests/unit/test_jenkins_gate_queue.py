"""The pre-push gate must not report a queued build as an unreachable controller.

`trigger.sh` already separates two states, and says so at the top of the file: a build that
FAILED and a gate that COULD NOT RUN need different responses. There is a third it did not
model -- the gate is WAITING.

`pips-ci` builds one at a time. A push made while another build is in flight finds its queue
item BLOCKED, and the controller is plainly reachable, because it is the thing answering the
poll that reports the block. The old wait was 120 polls x 2s = 240s against a build that takes
~885s, so *any* push during a build was guaranteed to fail -- and to fail by blaming the
controller. On 2026-09-04 that cost two pushes and sent this session to probe a controller that
was up the whole time and answering 200.

These tests drive the script against a stub controller, so they check what the gate DOES, not
what its source says.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TRIGGER = ROOT / "ops" / "jenkins" / "trigger.sh"

# The build this project actually runs takes ~885s. A queue wait shorter than one build cannot
# ever succeed while a build is in flight, which is the only time the wait matters.
ONE_BUILD_SECONDS = 885


class _StubServer(HTTPServer):
    """Carries the poll counter the handler increments."""

    seen_polls: int = 0
    base_url: str = ""


class _Controller(BaseHTTPRequestHandler):
    """A Jenkins just real enough for `trigger.sh` to talk to."""

    polls_blocked = 0  # how many queue polls report BLOCKED before a build is attached
    result = "SUCCESS"
    queue_http = 200  # non-200 => the controller stops answering queue polls mid-wait

    def log_message(self, *_args: Any) -> None:  # keep pytest output clean
        pass

    def _json(self, payload: dict[str, Any], code: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        # `buildWithParameters` answers with the queue item's Location -- the script reads the
        # header, not the body.
        server = self.server
        assert isinstance(server, _StubServer)
        self.send_response(201)
        self.send_header("Location", f"{server.base_url}/queue/item/1/")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        server = self.server
        assert isinstance(server, _StubServer)
        base = server.base_url
        if self.path.startswith("/crumbIssuer"):
            self._json({"crumbRequestField": "Jenkins-Crumb", "crumb": "stub"})
            return
        if self.path.startswith("/queue/item/1/api/json"):
            server.seen_polls += 1
            if type(self).queue_http != 200:
                self.send_response(type(self).queue_http)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            if server.seen_polls > type(self).polls_blocked:
                self._json({"executable": {"url": f"{base}/job/pips-ci/1/"}})
            # A BLOCKED item: no executable, and a `why` naming the build ahead of it. This is
            # the exact shape the real controller returned on 2026-09-04.
            self._json(
                {
                    "blocked": True,
                    "buildable": False,
                    "why": "Build #275 is already in progress (ETA: 9 min 40 sec)",
                }
            )
            return
        if re.match(r"^/job/pips-ci/1/api/json", self.path):
            self._json({"result": type(self).result})
            return
        if self.path.startswith("/job/pips-ci/1/consoleText"):
            body = b"stub console\n"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def run_trigger(
    *, polls_blocked: int, queue_wait: str, result: str = "SUCCESS", queue_http: int = 200
) -> subprocess.CompletedProcess[str]:
    _Controller.polls_blocked = polls_blocked
    _Controller.result = result
    _Controller.queue_http = queue_http
    port = _free_port()
    server = _StubServer(("127.0.0.1", port), _Controller)
    server.seen_polls = 0
    server.base_url = f"http://127.0.0.1:{port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = server.base_url
        return subprocess.run(
            ["bash", str(TRIGGER), "main"],
            capture_output=True,
            text=True,
            timeout=180,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                "JENKINS_URL": url,
                "PIPS_JENKINS_QUEUE_WAIT": queue_wait,
                "HOME": "/tmp",
                "TMPDIR": "/tmp",
            },
        )
    finally:
        server.shutdown()


def test_a_build_blocked_in_the_queue_is_waited_for_not_abandoned() -> None:
    """The gate must ride out a block: the controller is answering, the build is coming."""
    done = run_trigger(polls_blocked=3, queue_wait="60")
    assert done.returncode == 0, done.stderr
    assert "SUCCESS" in done.stdout


def test_a_still_queued_gate_is_not_reported_as_an_unreachable_controller() -> None:
    """Blocked past the deadline is still NOT 'could not reach' -- and must say which build."""
    done = run_trigger(polls_blocked=10_000, queue_wait="4")
    assert done.returncode == 3, done.stdout
    assert "could not reach the controller" not in done.stderr.lower()
    assert "#275" in done.stderr, done.stderr


def test_a_controller_that_is_truly_down_still_reports_unreachable() -> None:
    """The distinction only earns its keep if the real unreachable case still says so."""
    dead = f"http://127.0.0.1:{_free_port()}"
    done = subprocess.run(
        ["bash", str(TRIGGER), "main"],
        capture_output=True,
        text=True,
        timeout=120,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "JENKINS_URL": dead,
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
        },
    )
    assert done.returncode == 3
    assert "could not reach the controller" in done.stderr.lower()


def test_the_default_queue_wait_outlasts_a_single_build() -> None:
    """A wait shorter than one build can never succeed in the case it exists for."""
    text = TRIGGER.read_text(encoding="utf-8")
    match = re.search(r"PIPS_JENKINS_QUEUE_WAIT:-(\d+)", text)
    assert match, "the queue wait must be a named, overridable bound"
    assert int(match.group(1)) > ONE_BUILD_SECONDS, (
        f"queue wait {match.group(1)}s does not outlast one {ONE_BUILD_SECONDS}s build"
    )


def test_a_controller_that_goes_silent_mid_wait_is_unreachable_not_queued() -> None:
    """An EMPTY reason is not evidence of reachability.

    The queue POST succeeds, then the controller stops answering. There is no `why` to quote,
    so nothing has been learned about the build -- and reporting that as "still queued behind
    another build" would assert a fact the gate does not have. This is the same defect the
    whole file is about, pointed the other way: a state that was never observed must not be
    reported as one that was.
    """
    done = run_trigger(polls_blocked=10_000, queue_wait="4", queue_http=503)
    assert done.returncode == 3, done.stdout
    assert "could not reach the controller" in done.stderr.lower(), done.stderr
    assert "still queued" not in done.stderr.lower(), done.stderr


def test_a_missing_tool_is_not_reported_as_an_unreachable_controller() -> None:
    """Jenkins #276: the CI image installs curl but not jq, and the gate said this:

        /app/ops/jenkins/trigger.sh: line 51: jq: command not found
        pips-ci: could not reach the controller -- the crumb request failed; is the
                 controller up?

    The controller was a stub in the same process, and it was fine. This is the third instance
    of one shape in one script: a cause that was never observed, asserted as though it had
    been. A missing tool is a missing tool, and the gate must say so before it blames anything
    it cannot see.
    """
    with tempfile.TemporaryDirectory() as tmp:
        stunted = Path(tmp) / "bin"
        stunted.mkdir()
        # Everything the script needs EXCEPT jq, so the run fails for exactly one reason.
        for tool in ("bash", "curl", "awk", "tr", "seq", "sleep", "cat"):
            found = shutil.which(tool)
            if found:
                (stunted / tool).symlink_to(found)
        done = subprocess.run(
            ["bash", str(TRIGGER), "main"],
            capture_output=True,
            text=True,
            timeout=120,
            env={"PATH": str(stunted), "HOME": tmp, "TMPDIR": tmp},
        )
    assert done.returncode == 3, done.stdout
    assert "jq" in done.stderr, done.stderr
    assert "could not reach the controller" not in done.stderr.lower(), done.stderr


def test_the_ci_image_supplies_every_tool_the_gate_requires() -> None:
    """The script's requirement and the image's package list must not drift apart.

    They already did once: `curl` was installed, `jq` was not, and the tests for this very
    script could not run in CI. Read the requirement from the script rather than restating it
    here, so adding a tool to the preflight without adding it to the image fails loudly.
    """
    required = re.search(
        r"^for tool in ([a-z0-9 ]+); do$", TRIGGER.read_text(encoding="utf-8"), re.M
    )
    assert required, "the preflight must list its tools in one greppable place"
    dockerfile = (ROOT / "docker" / "research.Dockerfile").read_text(encoding="utf-8")
    apt = re.search(r"apt-get install -y --no-install-recommends \\\n(.*?)\\\n", dockerfile, re.S)
    assert apt, "could not find the apt package list"
    installed = set(apt.group(1).split())
    # `awk` ships in the base image via mawk/gawk; only packages named by the same name matter.
    missing = {t for t in required.group(1).split() if t not in installed} - {"awk"}
    assert not missing, f"the gate needs {sorted(missing)}, which the CI image does not install"
