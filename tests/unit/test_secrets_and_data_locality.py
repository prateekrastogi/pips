"""Where secrets and market data are allowed to live (rule 14, ADR-0011).

ADR-0011 relaxes rule 14 in exactly one direction: the Breeze session token may be committed
to this private repository. Everything else about rule 14 stands, and the parts that still
stand are the ones worth a test — a relaxation that quietly widens is how "just the token in
git" becomes "the token in every image we ship".

So: the token may be in git, and must NOT be in an image; market data may be on the VM, and
must NOT be in the repo.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA_ZONES = ("bronze", "silver", "gold", "quarantine", "snapshots", "universes")


def _ignore_lines(name: str) -> list[str]:
    path = ROOT / name
    # An explicit statement of the requirement beats a bare FileNotFoundError: this file
    # must be in the docker build context, or the guard silently cannot run where it matters.
    assert path.exists(), (
        f"{name} is missing from {ROOT} — it is a policy file these tests assert against, "
        "so it must not be excluded from the image build context (.dockerignore)"
    )
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


# ----------------------------------------------- the token may be in git (ADR-0011) -----


def test_env_is_no_longer_git_ignored() -> None:
    # ADR-0011 is a deliberate, recorded relaxation. Pinning it here means a later "tidy the
    # gitignore" cannot silently revert a decision that was made with its risks written down.
    assert ".env" not in _ignore_lines(".gitignore")


# --------------------------------------- ...and must never reach an image ---------------


def test_dockerignore_still_excludes_env() -> None:
    # The half of rule 14 that ADR-0011 does NOT relax. A token in git is a bounded risk the
    # owner accepted; a token baked into a distributed image is not the same risk at all.
    lines = _ignore_lines(".dockerignore")
    assert ".env" in lines
    assert ".env.*" in lines
    assert "!.env.example" in lines


@pytest.mark.parametrize(
    "dockerfile", sorted(p.name for p in (ROOT / "docker").glob("*.Dockerfile"))
)
def test_no_dockerfile_copies_the_env_file(dockerfile: str) -> None:
    text = (ROOT / "docker" / dockerfile).read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("COPY") and ".env" in stripped and ".env.example" not in stripped:
            pytest.fail(f"{dockerfile} copies an env file into the image: {stripped!r}")


# ------------------------------------------- market data lives on the VM, not here ------


@pytest.mark.parametrize("zone", DATA_ZONES)
def test_repo_data_zones_hold_no_market_data(zone: str) -> None:
    # Rule 14: ALL market data and runtime state live on arb-vm volumes; the laptop holds
    # code and fixtures only. These directories exist to shape the tree, not to hold data.
    path = ROOT / "data" / zone
    if not path.exists():
        return
    stray = [p.name for p in path.rglob("*") if p.is_file() and p.name != ".gitkeep"]
    assert stray == [], f"data/{zone} contains {stray} — market data belongs on the VM"


def test_the_data_root_is_the_vm_path_the_operator_can_see() -> None:
    """The data root must resolve to /srv/pips on the VM, by a path host tools can reach.

    This test previously asserted the OPPOSITE — that the data root must be a named volume —
    and that assertion was written before anything had been run. The first real campaign
    showed why it was wrong: compose prefixes volume names with the project, which it derives
    from the directory, so the same declaration produced `pips-data`, `checkout_pips-data` and
    `verify_pips-data` depending on where it was invoked. Six bronze records landed in a volume
    that the runbook, the systemd unit and any backup pointed nowhere near.

    Corrected rather than kept alongside the new one: two tests demanding opposite things is
    not coverage.
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    research = compose["services"]["research"]
    assert research["environment"]["PIPS_DATA_ROOT"] == "/srv/pips"
    mounts = [m for m in research["volumes"] if str(m).endswith(":/srv/pips")]
    assert mounts, "the research service must mount the data root"


def test_data_plane_services_load_the_tracked_env_file() -> None:
    """ADR-0011 put the Breeze data-plane token in the repo's `.env`; compose must read it.

    Found by running the first real campaign: the container raised KeyError('BREEZE_API_KEY')
    because compose was still pointing the data plane at the VM-side secrets file the ADR had
    superseded. The decision was recorded in docs and never wired, which is the failure mode a
    ledger exists to prevent and this test now covers.

    `env_file` is a RUNTIME read, not a build input — so this does not weaken the rule that
    `.env` never enters an image, which the tests above still enforce.
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name in ("research", "breeze-reader"):
        spec = compose["services"][name]
        env_files = spec.get("env_file") or []
        files = [env_files] if isinstance(env_files, str) else list(env_files)
        assert any(str(f).endswith(".env") and not str(f).startswith("/srv") for f in files), (
            f"{name} must load the repo's tracked .env (ADR-0011); it currently has {files}"
        )


def test_order_plane_credentials_are_not_in_the_tracked_env(
    strip_comments: Callable[[str], str],
) -> None:
    # ADR-0011 relaxed rule 14 for the DATA plane only. Rule 7 keeps the planes in separate
    # processes with separate credentials, so a broker secret appearing here would quietly
    # merge them — and put an order-plane credential in git, which the ADR did not authorise.
    env_path = ROOT / ".env"
    if not env_path.exists():
        # Inside the research image, and that is CORRECT: .dockerignore excludes .env so the
        # token never reaches a container image — the half of rule 14 ADR-0011 deliberately
        # kept. Unlike .gitignore, which was added to the build context when a guard needed
        # it, .env must stay out.
        #
        # So the check inverts rather than skipping: absence here must be CAUSED by the
        # exclusion, not by the file having quietly vanished. A plain skip would make this
        # test vacuous in CI, which is the one place it runs unattended.
        assert ".env" in strip_comments((ROOT / ".dockerignore").read_text(encoding="utf-8")), (
            ".env is absent but .dockerignore does not exclude it — it has gone missing for "
            "some other reason, and this guard would silently stop checking anything"
        )
        return

    env = strip_comments(env_path.read_text(encoding="utf-8"))
    for forbidden in ("FLATTRADE_API_KEY=", "FLATTRADE_API_SECRET=", "PIPS_LIVE=1"):
        assert forbidden not in env, f"{forbidden} must not appear in the tracked .env"


def test_the_data_root_is_a_host_bind_not_a_named_volume() -> None:
    """Market data must live at a stable, inspectable path on the VM.

    Found by running the first real campaign: the data root was a named volume, and compose
    prefixes volume names with the PROJECT — which it derives from the directory. Running from
    /srv/pips/checkout produced `checkout_pips-data`, a throwaway verification worktree
    produced `verify_pips-data`, and the bootstrap had created `pips-data`. Three volumes for
    one data root, and the six records the campaign wrote were invisible to every host tool
    pointed at /srv/pips — including the runbook, the systemd unit, and any backup.

    A bind mount makes the path mean the same thing to the container, the operator and the
    backup, regardless of which directory compose was invoked from.
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name, spec in compose["services"].items():
        mounts = [m for m in (spec.get("volumes") or []) if str(m).endswith(":/srv/pips")]
        if not mounts:
            continue
        source = str(mounts[0]).rsplit(":/srv/pips", 1)[0]
        assert "/" in source or source.startswith("$"), (
            f"{name} mounts a NAMED VOLUME at /srv/pips ({source!r}). Compose prefixes volume "
            "names with the project, so the same data root becomes a different volume "
            "depending on the directory it was run from."
        )


def test_compose_pins_an_explicit_project_name() -> None:
    # The other half of the same lesson, already learned once on the Jenkins controller: an
    # implicit project name is derived from the directory, and the directory changes.
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose.get("name"), "docker-compose.yml must set an explicit top-level name:"
