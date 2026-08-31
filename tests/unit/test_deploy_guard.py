"""Market-hours restart guard for the deploy rail [C-DEPLOY-01] (§2.2).

Research and data services roll on every main update. **Trading-path services never hot-swap
during market hours** — the rail holds their restart until after the close or before the open,
unless a human forces it.

This guard FAILS CLOSED, and that is the whole design. The donor this rail is ported from
(SAL-0010) carried a guard whose entire purpose was to avoid restarting mid-trade; it ran
`pgrep` inside a container that had no `procps`, the command exited 127, and the caller read
that as "not busy". The guard was inert and looked fine. Every uncertainty here therefore
resolves to *defer*: an unknown service is treated as trading-path, and an unreadable calendar
blocks rather than waves through.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pips.core.calendar import load_calendar
from pips.core.time import ts_from_iso
from pips.ops.deploy_guard import (
    ROLLING_SERVICES,
    TRADING_PATH_SERVICES,
    restart_decision,
)

ROOT = Path(__file__).resolve().parents[2]
CAL = load_calendar(ROOT / "config" / "calendars" / "nse_equity.yaml")
TRADING_DAY = "2026-06-01"  # a Monday
WEEKEND = "2026-06-06"  # a Saturday


def at(day: str, clock: str) -> int:
    return ts_from_iso(f"{day}T{clock}")


@pytest.mark.parametrize(
    ("clock", "permitted"),
    [
        ("08:44:59", True),  # before the protected window opens
        ("08:45:00", False),  # window opens
        ("12:00:00", False),
        ("15:34:59", False),
        ("15:35:00", True),  # after the close, per §2.2
        ("23:00:00", True),
    ],
)
def test_the_protected_window_is_0845_to_1535(clock: str, permitted: bool) -> None:
    d = restart_decision("breeze-reader", at(TRADING_DAY, clock), CAL)
    assert d.permitted is permitted, d.reason


def test_a_non_trading_day_is_always_open_for_restarts() -> None:
    assert restart_decision("live-engine", at(WEEKEND, "12:00:00"), CAL).permitted is True


@pytest.mark.parametrize("service", sorted(ROLLING_SERVICES))
def test_research_and_data_services_roll_even_mid_session(service: str) -> None:
    d = restart_decision(service, at(TRADING_DAY, "12:00:00"), CAL)
    assert d.permitted is True, d.reason


@pytest.mark.parametrize("service", sorted(TRADING_PATH_SERVICES))
def test_every_trading_path_service_is_held_mid_session(service: str) -> None:
    assert restart_decision(service, at(TRADING_DAY, "12:00:00"), CAL).permitted is False


def test_an_unknown_service_is_treated_as_trading_path() -> None:
    # FAIL CLOSED. A service added to compose but not to either list must be held, not waved
    # through — the donor's inert guard is what happens when the unknown case defaults to
    # "fine". Being wrong here costs a deferred deploy; being wrong the other way restarts
    # the order plane mid-session.
    d = restart_decision("some-new-service", at(TRADING_DAY, "12:00:00"), CAL)
    assert d.permitted is False
    assert "unknown" in d.reason.lower()


def test_the_two_service_lists_do_not_overlap() -> None:
    assert set() == TRADING_PATH_SERVICES & ROLLING_SERVICES


def test_a_human_force_is_permitted_but_names_the_recovery_path() -> None:
    # §2.2 allows a forced intraday restart, and requires it to follow the crash-recovery
    # path (journal replay + broker reconciliation, §3.13) like any other restart.
    d = restart_decision("live-engine", at(TRADING_DAY, "12:00:00"), CAL, force=True)
    assert d.permitted is True
    assert "journal" in d.reason.lower() and "reconcil" in d.reason.lower()


def test_a_deferred_decision_says_when_it_will_be_permitted() -> None:
    d = restart_decision("breeze-reader", at(TRADING_DAY, "12:00:00"), CAL)
    assert d.permitted is False
    assert "15:35" in d.reason


def test_an_unreadable_calendar_defers_rather_than_proceeding() -> None:
    # The uncertainty case. If we cannot tell whether it is market hours, it is market hours.
    d = restart_decision("breeze-reader", at(TRADING_DAY, "12:00:00"), calendar=None)
    assert d.permitted is False
    assert "calendar" in d.reason.lower()


def test_an_unverified_holiday_list_errs_toward_deferring() -> None:
    # The shipped calendar has an empty, unverified holiday list, so it can only ever
    # OVER-report trading days — never under-report one. Over-reporting defers a restart,
    # which is the safe direction. Pinned so a future holiday source cannot silently invert it.
    assert CAL.holidays_verified is False
    assert CAL.is_trading_day(date(2026, 6, 1)) is True  # a real trading Monday
    # If 2026-06-01 were in fact a holiday, the empty list would still call it a trading day,
    # and the guard would DEFER a restart it could have allowed. Wrong in the safe direction.
    assert restart_decision("live-engine", at(TRADING_DAY, "12:00:00"), CAL).permitted is False


# ------------------------------------ the rail's service set must be real ---------------


def test_every_service_the_rail_promotes_exists_in_the_compose_file() -> None:
    """The rail must not discover a missing service mid-promotion.

    It did exactly that on its first real deploy: it promoted `research-runner`, then failed
    on `backfill`, which sync.sh lists but docker-compose.yml does not define. The result was
    a PARTIAL promotion followed by an abort — the one outcome the donor's fourth safety
    property (SAL-0010: "no partial promotion, no retry storm") exists to prevent.

    The fix is to validate the whole set before touching anything, and this is the test that
    keeps the two files honest with each other.
    """

    # BOTH scripts, because the first version of this test checked only sync.sh — and
    # rollback.sh carried the identical hardcoded list, drifted the identical way, and tried
    # to restore services compose does not define. A guard that covers one of two copies of
    # the same bug is a guard that will let the other one through.
    #
    # COMMENTS ARE STRIPPED FIRST. This is the second time a text-matching guard in this
    # repository has fired on prose that DOCUMENTS the very thing it forbids — the
    # Corwin-Schultz check did it, and was rewritten to scan the AST for the same reason.
    # A guard that punishes writing down why something is forbidden teaches people to delete
    # the explanation, so it must inspect code and ignore commentary.
    def code_only(text: str) -> str:
        return "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))

    for name in ("sync.sh", "rollback.sh"):
        script = code_only((ROOT / "ops" / "deploy" / name).read_text(encoding="utf-8"))
        assert "config --services" in script, (
            f"{name} must ask compose which services exist rather than keeping its own list"
        )
        for stale in ("ROLLING_SERVICES=", "TRADING_PATH_SERVICES="):
            assert stale not in script, f"{name} still hardcodes {stale} — it will drift again"
        assert "backfill" not in script and "telemetry" not in script, (
            f"{name} names services compose does not define"
        )

    sync = (ROOT / "ops" / "deploy" / "sync.sh").read_text(encoding="utf-8")

    # And it must validate the whole set before promoting any of it.
    promote_at = sync.index("for s in $PROMOTABLE; do promote")
    assert "refusing to promote a partial set" in sync[:promote_at], (
        "the set must be validated BEFORE the first promotion, or a mid-promotion discovery "
        "leaves the fleet half-deployed"
    )


def test_the_guards_service_classes_cover_every_compose_service() -> None:
    # The other direction: a service defined in compose but classified by neither list falls
    # through to "unknown", which the guard treats as trading-path. That is the safe default,
    # but it should be a deliberate choice rather than an oversight.
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    unclassified = set(compose["services"]) - TRADING_PATH_SERVICES - ROLLING_SERVICES
    assert not unclassified, (
        f"{sorted(unclassified)} are defined in compose but classified by neither list — "
        "they would be treated as trading-path by the fail-closed default, which is safe "
        "but should be explicit"
    )


def test_the_rail_reexecs_itself_after_updating_the_checkout() -> None:
    """A deploy script that updates the checkout it lives in must re-exec.

    Bash reads a script lazily, by byte offset. `git merge --ff-only` rewrites `sync.sh`
    underneath the running shell, which then continues reading at its saved offset in a file
    whose contents have shifted. Observed live: a run began on the old script, pulled in a fix
    to that same script, and carried on executing the OLD logic — promoting a service the new
    version had already removed. The benign outcome was a failed deploy; the general case is
    arbitrary corruption, because the offset lands wherever it lands.
    """
    sync = (ROOT / "ops" / "deploy" / "sync.sh").read_text(encoding="utf-8")
    assert "exec " in sync and "PIPS_DEPLOY_REEXEC" in sync, (
        "sync.sh must re-exec itself after the fast-forward, with a guard flag so it cannot loop"
    )
    # The re-exec must happen AFTER the merge and BEFORE anything is built or promoted.
    merge_at = sync.index("git merge --ff-only")
    reexec_at = sync.index("PIPS_DEPLOY_REEXEC=1 exec")
    build_at = sync.index('docker compose -f "$COMPOSE_FILE" build')
    assert merge_at < reexec_at < build_at, (
        "the re-exec must sit between the fast-forward and the first build"
    )


def test_the_rail_asks_compose_with_the_vm_profile() -> None:
    # The trading-path and research services are all under `profiles: ["vm"]`, so a plain
    # `config --services` reports only `research` — and the rail would find nothing to
    # promote while looking like it had succeeded.
    sync = (ROOT / "ops" / "deploy" / "sync.sh").read_text(encoding="utf-8")
    assert "COMPOSE_PROFILES" in sync, (
        "sync.sh must select the vm profile, or compose reports only the build container"
    )


def test_no_one_shot_service_is_set_to_restart_forever() -> None:
    """A container whose command exits immediately must not carry `restart: unless-stopped`.

    Observed live: `research-runner` runs `python -m pips.cli --help`, exits 0, and was
    restarted forever — a crash-loop that burns CPU and fills the journal while looking, in
    `docker ps`, like a service that is merely "Restarting". It has no real workload until
    M4, and giving it a fake long-running command to silence the loop would be worse: the
    health check would then report a healthy service that does nothing.
    """
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    one_shot_markers = ("--help", "--version")
    for name, spec in compose["services"].items():
        command = " ".join(spec.get("command", []) or [])
        if any(marker in command for marker in one_shot_markers):
            assert spec.get("restart", "no") in ("no", None), (
                f"{name} runs a one-shot command ({command!r}) but is set to "
                f"restart={spec.get('restart')!r} — that is a crash-loop, not a service"
            )


def test_the_reexec_does_not_skip_the_work_it_was_re_execed_to_do() -> None:
    """After re-execing, the checkout is already at the target — so the "nothing to do"
    early exit would fire and the deploy would never happen.

    Observed live: the rail fast-forwarded, re-execed correctly, and the second process
    reported "already at 481aafe; nothing to do" and finished cleanly having built nothing and
    promoted nothing. It had fixed the self-modification hazard by never deploying — and
    logged a successful-looking "Finished" while doing it. A silent no-op that reports success
    is worse than the loud failure it replaced, because nothing prompts anyone to look.
    """
    sync = (ROOT / "ops" / "deploy" / "sync.sh").read_text(encoding="utf-8")
    lines = sync.splitlines()
    early_exit = next(
        (
            i
            for i, line in enumerate(lines)
            if "nothing to do" in line and line.strip().startswith("log")
        ),
        None,
    )
    assert early_exit is not None, "sync.sh no longer has the up-to-date early exit"
    # The guard must sit on the condition immediately above the log line.
    window = "\n".join(lines[max(0, early_exit - 3) : early_exit + 1])
    assert "PIPS_DEPLOY_REEXEC" in window, (
        "the 'nothing to do' exit must be guarded by the re-exec flag, or a re-execed run "
        "skips the very deploy it was re-execed to perform"
    )


def test_the_compose_fallback_tag_is_the_one_the_rail_publishes() -> None:
    """A manual `docker compose run` must not resolve to a stale image.

    Found by following our own runbook: `docker compose run research ...` on the VM resolved
    to `pips/research:dev`, an hour-old build from before the command being invoked existed.
    The rail publishes SHA-tagged images, so nothing was refreshing the fallback tag — an
    operator gets old code, silently, and for a data campaign that means bronze written by an
    outdated normalizer.

    The fix is structural rather than a runbook note: the rail republishes the fallback tag
    after a successful deploy. This test keeps the two files from drifting apart, which is the
    same failure the service-list guard above exists for.
    """
    import re

    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    images = [s.get("image", "") for s in compose["services"].values() if s.get("image")]
    fallbacks = {
        m.group(1) for image in images if (m := re.search(r"\$\{PIPS_SHA:-([^}]+)\}", image))
    }
    assert fallbacks, "compose must give PIPS_SHA a fallback tag"

    sync = (ROOT / "ops" / "deploy" / "sync.sh").read_text(encoding="utf-8")
    for tag in fallbacks:
        assert f":{tag}" in sync, (
            f"compose falls back to ':{tag}' but sync.sh never publishes it — a manual "
            "`docker compose run` would resolve to whatever stale image happens to carry "
            "that tag"
        )
