"""The image must be able to prove what it contains  (gate integrity, rule 10).

`docker compose run research make ci` — the command CLAUDE.md names as THE way to verify —
printed `ci: green` from an image built the previous day from a different commit, whose
`validation/` package predated two whole milestones. 511 tests passed and nothing in the output
distinguished that from a real green. The compose service resolves
``image: pips/research:${PIPS_SHA:-current}`` with no bind mount and no build on run, so every
laptop invocation gets a floating tag that nothing keeps current.

Fixing the tag would fix today's instance. The defect is that **a verify of unknown provenance
still reported a verdict**, which is this project's recurring failure shape: the sealed lockbox
returning a filtered series, a rate-limited 200 recorded as "no data", ``NOT_RUN`` read as
``PASSED``. So the check lives at the point of use. Before the ladder runs, the image states
which commit it was built from and the caller states which commit it believes it is testing,
and a green is only reachable when those agree.

**Three states, not two.** Running on the HOST is not running in an image: the working tree is
right there and nothing can be stale, so there is nothing to check and a stray expectation in
someone's shell must not start failing host runs. Running in an image that cannot NAME its
commit is a third thing, and it must not be mistaken for the host however similar it looks from
inside — collapsing those two would restore the whole hole the moment someone forgets the
build arg.

Prefix matching is allowed with a floor of seven characters. It is a convenience for humans
reading short SHAs, and without the floor it is a way to pass a value that matches almost
anything: a one-character prefix matches roughly one commit in sixteen.
"""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass

__all__ = ["ProvenanceError", "ProvenanceReport", "Verdict", "check_provenance", "main"]

MIN_ABBREV = 7
IMAGE_MARKER = "/app/.pips-image-sha"
_SUPPLIER = "make ci-container"


class ProvenanceError(RuntimeError):
    """The ladder must not run. There is deliberately no way to downgrade this to a warning."""


class Verdict(enum.Enum):
    NOT_IN_IMAGE = "NOT_IN_IMAGE"
    """On the host. The working tree is the thing under test; staleness is not possible."""

    MATCH = "MATCH"
    """The image was built from the commit the caller believes it is testing."""


@dataclass(frozen=True)
class ProvenanceReport:
    verdict: Verdict
    image_sha: str | None
    expected_sha: str | None
    dirty: bool

    def describe(self) -> str:
        """One line, printed before the ladder, so a green says what it covered."""
        if self.verdict is Verdict.NOT_IN_IMAGE:
            return "provenance: running on the host, not in a pips image"
        suffix = " (working tree DIRTY at build time)" if self.dirty else ""
        return f"provenance: image built from {self.image_sha}{suffix}"


def _clean(value: str | None) -> str | None:
    """Normalise, and collapse the empty string to None.

    compose writes ``${PIPS_EXPECTED_SHA:-}``, which reaches the process as ``""`` rather than
    unset. Comparing raw strings would let two absences agree with each other and report a
    match.
    """
    if value is None:
        return None
    stripped = value.strip().lower()
    return stripped or None


def check_provenance(
    *,
    in_image: bool,
    image_sha: str | None,
    expected_sha: str | None,
    dirty: bool = False,
) -> ProvenanceReport:
    """Raise unless the image can prove it holds the commit the caller means to test."""
    image = _clean(image_sha)
    expected = _clean(expected_sha)

    if not in_image:
        return ProvenanceReport(Verdict.NOT_IN_IMAGE, None, expected, dirty)

    if image is None:
        raise ProvenanceError(
            "this image was built without provenance: it carries no commit id, so it cannot "
            "say what it holds. That is NOT the same as running on the host, where the working "
            "tree is the thing under test. Rebuild passing --build-arg PIPS_SHA=<commit>."
        )

    if expected is None:
        raise ProvenanceError(
            f"refusing to verify: this image was built from {image[:12]}, and no expectation "
            "was supplied to check it against. A verify of unknown provenance is how a "
            f"day-old image reported `ci: green`. Run `{_SUPPLIER}`, which builds the image "
            "from the working tree and passes the commit it built."
        )

    if len(expected) < MIN_ABBREV:
        raise ProvenanceError(
            f"expected commit {expected!r} is too short to identify one: an abbreviation must "
            f"be at least {MIN_ABBREV} characters. A shorter prefix matches many commits, so a "
            "match against it means nothing."
        )

    if not image.startswith(expected):
        raise ProvenanceError(
            f"STALE IMAGE. This image was built from {image[:12]}, but the caller is verifying "
            f"{expected[:12]}. The ladder would have run against code that is not the code "
            "under test, and reported green for it. Rebuild: `" + _SUPPLIER + "`."
        )

    return ProvenanceReport(Verdict.MATCH, image, expected, dirty)


def main(argv: list[str] | None = None) -> int:
    """`python -m pips.cli provenance` — the preflight `make ci` runs before the ladder."""
    del argv
    marker = os.environ.get("PIPS_IMAGE_SHA")
    in_image = marker is not None or os.path.exists(IMAGE_MARKER)
    if marker is None and in_image:
        with open(IMAGE_MARKER, encoding="utf-8") as handle:
            marker = handle.read()

    try:
        report = check_provenance(
            in_image=in_image,
            image_sha=marker,
            expected_sha=os.environ.get("PIPS_EXPECTED_SHA"),
            dirty=os.environ.get("PIPS_IMAGE_DIRTY", "") == "1",
        )
    except ProvenanceError as error:
        print(f"provenance: REFUSED\n{error}")
        return 1
    print(report.describe())
    return 0
