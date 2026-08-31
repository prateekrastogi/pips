"""The CI controller must not be able to adopt another project's containers.

Compose derives its project name from the DIRECTORY when none is set, and this repo's
``ops/jenkins`` shares that basename with a neighbouring project's ``deploy/jenkins``. On
the first `make jenkins-up` the two resolved to the same project and service, and bringing
pips up adopted and replaced the other controller's container and image. Nothing about it
was visible at the time: compose printed one `Recreated` line inside an otherwise
successful build.

These are the tripwires for that incident (BLK-0001).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_COMPOSE = ROOT / "ops" / "jenkins" / "docker-compose.yml"


@pytest.fixture
def ci_compose() -> dict[str, Any]:
    return dict(yaml.safe_load(CI_COMPOSE.read_text(encoding="utf-8")))


def test_ci_compose_pins_an_explicit_project_name(ci_compose: dict[str, Any]) -> None:
    assert ci_compose.get("name"), (
        "ops/jenkins/docker-compose.yml must set an explicit top-level `name:`. Without it "
        "compose uses the directory name ('jenkins'), which collides with other projects "
        "that also keep their controller in a directory called jenkins."
    )


def test_every_ci_service_pins_an_explicit_image_name(ci_compose: dict[str, Any]) -> None:
    for service, spec in ci_compose["services"].items():
        assert spec.get("image"), (
            f"service {service!r} must pin an explicit `image:`. The default is "
            "'<project>-<service>', which collides exactly as silently as the container did."
        )


def test_ci_container_and_volume_names_are_pips_scoped(ci_compose: dict[str, Any]) -> None:
    for service, spec in ci_compose["services"].items():
        assert spec.get("container_name", "").startswith("pips-"), (
            f"service {service!r} must pin a pips-scoped container_name"
        )
    for volume, spec in (ci_compose.get("volumes") or {}).items():
        name = (spec or {}).get("name", volume)
        assert name.startswith("pips"), f"volume {volume!r} resolves to {name!r}, not pips-scoped"


def test_ci_controller_is_loopback_only(ci_compose: dict[str, Any]) -> None:
    # A controller with a mounted docker socket is root-equivalent on this host. Publishing
    # it on 0.0.0.0 would put that on the LAN behind a placeholder password.
    for service, spec in ci_compose["services"].items():
        for port in spec.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), (
                f"service {service!r} publishes {port!r}; the CI controller must bind loopback only"
            )
