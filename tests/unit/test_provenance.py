"""The image must be able to prove what it contains  (gate integrity, rule 10).

`docker compose run research make ci` printed `ci: green` from an image built the previous day
from a different commit, whose `validation/` package predated two whole milestones. 511 tests
passed and nothing in the output distinguished that from a real green. The compose service
resolves `image: pips/research:${PIPS_SHA:-current}` with no bind mount and no build on run, so
every laptop invocation gets a floating tag that nothing keeps current.

Fixing the tag would fix today's instance. The defect is that **a verify of unknown provenance
still reported a verdict** — the same shape as the sealed lockbox handing back a filtered
series, or a rate-limited 200 recorded as "no data". So the check lives at the point of use:
before the ladder runs, the image states which commit it was built from and the caller states
which commit it believes it is testing, and a green is only possible when those agree.

The three-way distinction is the whole design. Running on the HOST is not running in an image,
so nothing can be stale and there is nothing to check. Running in an image that cannot name its
commit is not the same as running on the host, however similar the two look from inside.
"""

from __future__ import annotations

import pytest

from pips.ops.provenance import ProvenanceError, Verdict, check_provenance, main

SHA = "62d1a3e7947d4a1e8b0c9f3a5d6e7b8c9a0f1e2d"
OTHER = "4d4916f0a1b2c3d4e5f60718293a4b5c6d7e8f90"


# ------------------------------------------------------------ on the host -------------


def test_running_outside_an_image_is_not_a_provenance_question() -> None:
    """`make ci` on the laptop tests the working tree directly. Nothing can be stale."""
    report = check_provenance(in_image=False, image_sha=None, expected_sha=None)
    assert report.verdict is Verdict.NOT_IN_IMAGE


def test_an_expectation_on_the_host_is_still_not_a_provenance_question() -> None:
    # A stray PIPS_EXPECTED_SHA in someone's shell must not start failing host-side runs.
    report = check_provenance(in_image=False, image_sha=None, expected_sha=OTHER)
    assert report.verdict is Verdict.NOT_IN_IMAGE


# ------------------------------------------------------------ in an image -------------


def test_an_image_that_matches_the_expectation_passes() -> None:
    report = check_provenance(in_image=True, image_sha=SHA, expected_sha=SHA)
    assert report.verdict is Verdict.MATCH
    assert report.image_sha == SHA


def test_a_stale_image_is_refused_and_the_message_names_both_commits() -> None:
    """The actual defect. The message has to carry both, or the reader cannot tell which."""
    with pytest.raises(ProvenanceError) as excinfo:
        check_provenance(in_image=True, image_sha=OTHER, expected_sha=SHA)
    message = str(excinfo.value)
    assert OTHER[:12] in message
    assert SHA[:12] in message


def test_an_image_asked_to_verify_without_an_expectation_is_refused() -> None:
    """Unknown provenance is not permission to report a verdict.

    Passing nothing is how the stale image produced its green: there was no expectation for it
    to contradict. The refusal names the target that supplies one, so the fix is to pass the
    right SHA rather than to find a value that quiets the check.
    """
    with pytest.raises(ProvenanceError, match="ci-container"):
        check_provenance(in_image=True, image_sha=SHA, expected_sha=None)


def test_an_image_built_without_provenance_is_refused_not_mistaken_for_the_host() -> None:
    """An image whose marker is present but empty built without the build arg.

    It is NOT a host run. Treating a missing SHA as 'not in an image' would restore the exact
    hole this closes: forget the `--build-arg` and every stale image goes quiet again.
    """
    with pytest.raises(ProvenanceError, match="built without"):
        check_provenance(in_image=True, image_sha=None, expected_sha=SHA)


# ------------------------------------------------------------ the empty string --------


def test_an_empty_expectation_is_unset_not_a_match() -> None:
    """compose writes `${PIPS_EXPECTED_SHA:-}`, which reaches the process as "" and not unset.

    Comparing raw strings would make "" == "" a MATCH for an image that also failed to bake a
    SHA — two absences agreeing with each other and reporting green.
    """
    with pytest.raises(ProvenanceError):
        check_provenance(in_image=True, image_sha=SHA, expected_sha="")
    with pytest.raises(ProvenanceError, match="built without"):
        check_provenance(in_image=True, image_sha="", expected_sha="")


def test_whitespace_around_a_sha_does_not_change_the_verdict() -> None:
    # The marker is written with `echo`, so it arrives with a trailing newline.
    report = check_provenance(in_image=True, image_sha=f"  {SHA}\n", expected_sha=SHA)
    assert report.verdict is Verdict.MATCH


def test_the_comparison_ignores_case() -> None:
    report = check_provenance(in_image=True, image_sha=SHA.upper(), expected_sha=SHA)
    assert report.verdict is Verdict.MATCH


# ------------------------------------------------------------ abbreviations -----------


def test_an_abbreviated_expectation_matches_on_prefix() -> None:
    report = check_provenance(in_image=True, image_sha=SHA, expected_sha=SHA[:7])
    assert report.verdict is Verdict.MATCH


def test_an_abbreviation_shorter_than_seven_is_refused() -> None:
    """A one-character prefix matches roughly one commit in sixteen.

    Prefix matching is a convenience for humans reading short SHAs; without a floor it is a way
    to pass a value that matches almost anything, which is a green that means nothing.
    """
    with pytest.raises(ProvenanceError, match="too short"):
        check_provenance(in_image=True, image_sha=SHA, expected_sha=SHA[:4])


def test_a_prefix_that_does_not_match_is_still_refused() -> None:
    with pytest.raises(ProvenanceError):
        check_provenance(in_image=True, image_sha=SHA, expected_sha=OTHER[:8])


# ------------------------------------------------------------ dirty trees -------------


def test_a_dirty_build_is_reported_and_does_not_by_itself_refuse() -> None:
    """Locally you WANT to verify uncommitted work; the SHA is then not the whole truth.

    Refusing would make the check useless for the loop it is meant to protect. Reporting it
    keeps the green honest about what it covered — Jenkins answers the pushed-SHA question.
    """
    report = check_provenance(in_image=True, image_sha=SHA, expected_sha=SHA, dirty=True)
    assert report.verdict is Verdict.MATCH
    assert report.dirty is True
    assert "dirty" in report.describe().lower()


def test_the_description_states_the_commit_so_a_green_says_what_it_covered() -> None:
    report = check_provenance(in_image=True, image_sha=SHA, expected_sha=SHA)
    assert SHA[:12] in report.describe()


# ------------------------------------------------------------ the wiring ---------------
#
# `main` is what `make ci` actually calls. A fault here makes the whole check dead while every
# test above stays green — which is precisely how `check_unexplained_ratio_jump` survived a
# milestone.


def test_main_passes_on_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPS_IMAGE_SHA", raising=False)
    monkeypatch.delenv("PIPS_EXPECTED_SHA", raising=False)
    monkeypatch.setattr("pips.ops.provenance.IMAGE_MARKER", "/nonexistent/.pips-image-sha")
    assert main([]) == 0


def test_main_passes_in_a_matching_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPS_IMAGE_SHA", SHA)
    monkeypatch.setenv("PIPS_EXPECTED_SHA", SHA)
    assert main([]) == 0


def test_main_refuses_a_stale_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPS_IMAGE_SHA", OTHER)
    monkeypatch.setenv("PIPS_EXPECTED_SHA", SHA)
    assert main([]) == 1


def test_main_refuses_an_image_with_no_expectation(monkeypatch: pytest.MonkeyPatch) -> None:
    # The exact shape of the original defect: compose supplies no expectation, so the old
    # command is refused rather than answered.
    monkeypatch.setenv("PIPS_IMAGE_SHA", SHA)
    monkeypatch.setenv("PIPS_EXPECTED_SHA", "")
    assert main([]) == 1


def test_main_treats_an_empty_baked_sha_as_an_image_not_a_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ENV PIPS_IMAGE_SHA=` with an empty build arg reaches the process as "", not unset.

    `os.environ.get` returns "" there, which is falsy — reading it as absent would classify the
    image as a host run and wave it through.
    """
    monkeypatch.setenv("PIPS_IMAGE_SHA", "")
    monkeypatch.setenv("PIPS_EXPECTED_SHA", SHA)
    assert main([]) == 1
