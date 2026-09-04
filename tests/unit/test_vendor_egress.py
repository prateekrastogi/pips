"""Vendor API calls may only leave from the whitelisted host (`[C-DATA-01]`, rule 14).

ICICI whitelists ONE IP for API calls, and it is arb-vm's. The owner stated it plainly on
2026-09-04: *"make sure everything data related is done on vm as only that ip is whitelisted"*.

Until now that was a habit, not a rule the code could keep. `build_session` would happily
construct a client anywhere; run from a laptop it reaches the vendor from an address ICICI does
not know, and what comes back is an auth-shaped failure that looks like a bad token — sending
the reader to rotate a credential that was never the problem. This session already lost two
pushes to a gate that misreported its own failure; the same shape is not worth repeating on the
data plane.

SAL-0001's donor drew the distinction this guard is careful to preserve: only API **calls** need
the whitelisted egress. The interactive login that mints the daily token is a browser session and
can happen anywhere, which is why the runbook has a human on a laptop and the fetch on the VM.

This is a guard against ACCIDENT, not an attacker: anything that can set an environment variable
can pass it. Its job is to make the rule unforgettable, and to fail with the reason attached.
"""

from __future__ import annotations

import pytest

from pips.data.breeze.client import EGRESS_ENV, VendorEgressError, build_session


def test_a_vendor_session_is_refused_off_the_whitelisted_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(EGRESS_ENV, raising=False)
    with pytest.raises(VendorEgressError) as raised:
        build_session()
    message = str(raised.value)
    assert "whitelist" in message.lower()
    assert "arb-vm" in message, "the message must say WHERE to run it, not only that this is wrong"


def test_the_guard_runs_before_the_api_key_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """ORDER IS THE POINT.

    On a laptop the credentials are usually absent too. If the key were read first, the operator
    would get `KeyError: 'BREEZE_API_KEY'` — a missing-credential error for a
    wrong-host problem — and would go hunting for a token. The egress refusal has to come first
    so the message describes the actual fault.
    """
    monkeypatch.delenv(EGRESS_ENV, raising=False)
    monkeypatch.delenv("BREEZE_API_KEY", raising=False)
    with pytest.raises(VendorEgressError):
        build_session()


def test_the_marker_lets_the_call_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must be passable, or it is just a broken fetcher.

    Past the guard the next thing `build_session` needs is the API key, so a missing key is the
    proof that egress was allowed. Asserting the *specific* next failure, not merely "not
    VendorEgressError", which would also hold for a guard that raised nothing and did nothing.
    """
    monkeypatch.setenv(EGRESS_ENV, "arb-vm")
    monkeypatch.delenv("BREEZE_API_KEY", raising=False)
    with pytest.raises(KeyError, match="BREEZE_API_KEY"):
        build_session()


def test_an_empty_marker_is_not_a_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """`PIPS_VENDOR_EGRESS=` reaches the process as "" — unset, wearing a value's clothes."""
    monkeypatch.setenv(EGRESS_ENV, "   ")
    with pytest.raises(VendorEgressError):
        build_session()


def test_the_vm_services_actually_set_the_marker() -> None:
    """The guard and the environment that satisfies it must not drift apart.

    This guard is unusual: getting it wrong does not fail open, it fails CLOSED and stops every
    fetch on the VM. So the binding is checked from the compose file rather than assumed — a
    service that talks to Breeze and lacks the marker is a data plane that refuses itself.

    Read out of `client.py`'s own constant, so renaming it without updating compose fails here
    rather than at 05:00 on the VM.
    """
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    # The services that construct a vendor session: the research image runs backfill/capture,
    # and breeze-reader is the live tick process.
    for name in ("research", "breeze-reader"):
        env = services[name].get("environment") or {}
        assert EGRESS_ENV in env, (
            f"service {name!r} makes vendor calls but does not set {EGRESS_ENV}"
        )
        assert str(env[EGRESS_ENV]).strip(), f"service {name!r} sets {EGRESS_ENV} to an empty value"
