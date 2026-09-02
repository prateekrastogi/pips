"""§4.2's survivorship audit, which is a promotion blocker  (`[C-UNIV-04]`).

The blueprint states it in a box:

> If the available history contains only currently listed names or current broker eligibility,
> label every result survivorship-biased. **No candidate may be promoted** until listings,
> delistings, token changes, corporate actions and daily eligibility have adequate archival
> coverage.

Two claims, and the second is the one with teeth. A survivorship-biased backtest is not a
caveat to note in a dossier — it is a bar on promotion, because the bias is not a wide error
band. It is a systematic lift in one direction: the names that failed are simply absent, so
every strategy looks better than it was, and no amount of downstream statistics recovers what
was never in the panel.

**Biased and may-promote cannot disagree.** They are derived from one source rather than stored
side by side, for the same reason `Measurement` has no verdict field: two facts that must agree
will eventually not, and the reader trusts whichever one flatters.

**Unknown coverage blocks.** "We did not check whether delistings are covered" is not
"delistings are covered", and treating them alike is how a survivorship-biased panel gets
promoted by a missing file.
"""

from __future__ import annotations

import dataclasses

import pytest

from pips.universe.survivorship import (
    REQUIRED_COVERAGE,
    ArchivalCoverage,
    survivorship_audit,
)


def coverage(**over: bool | None) -> ArchivalCoverage:
    """Full coverage, then `over` applied — built from REQUIRED_COVERAGE so a sixth requirement
    added to the model appears here without anyone remembering."""
    base: dict[str, bool | None] = dict.fromkeys(REQUIRED_COVERAGE, True)
    base.update(over)
    return ArchivalCoverage(**base)


# ------------------------------------------------------------------- the clean case -----


def test_full_archival_coverage_permits_promotion() -> None:
    verdict = survivorship_audit(coverage())
    assert not verdict.biased
    assert verdict.may_promote
    assert verdict.missing == () and verdict.undetermined == ()


# ---------------------------------------------------------- the two cannot disagree -----


def test_there_is_no_field_to_store_a_contradiction_in() -> None:
    """Structural, and the same argument as `Measurement` having no verdict field.

    `biased` and `may_promote` are derived. Stored independently they would eventually
    disagree, and a reader shown "survivorship-biased, promotable" believes the half that lets
    the work proceed.
    """
    stored = {f.name for f in dataclasses.fields(survivorship_audit(coverage()))}
    assert "biased" not in stored
    assert "may_promote" not in stored


@pytest.mark.parametrize("field", sorted(REQUIRED_COVERAGE))
def test_any_gap_blocks_promotion_and_labels_the_result(field: str) -> None:
    verdict = survivorship_audit(coverage(**{field: False}))
    assert verdict.biased
    assert not verdict.may_promote, "the blueprint's bar is on promotion, not on the label"
    assert field in " ".join(verdict.missing)


@pytest.mark.parametrize("field", sorted(REQUIRED_COVERAGE))
def test_unknown_coverage_blocks_too(field: str) -> None:
    """ "We did not check" is not "it is covered"."""
    verdict = survivorship_audit(coverage(**{field: None}))
    assert verdict.biased
    assert not verdict.may_promote
    assert field in " ".join(verdict.undetermined)
    assert verdict.missing == (), "a gap in the check is not a gap in the archive"


# ------------------------------------------------------------------- completeness -----


def test_every_field_of_the_box_is_required() -> None:
    """Enumerated from the model rather than listed here, so a sixth requirement added later is
    audited without anyone remembering — and pinned against the blueprint's own wording."""
    assert set(REQUIRED_COVERAGE) == {
        "listings",
        "delistings",
        "token_changes",
        "corporate_actions",
        "daily_eligibility",
    }
    assert {f.name for f in dataclasses.fields(ArchivalCoverage)} == set(REQUIRED_COVERAGE)


def test_every_gap_is_reported_at_once() -> None:
    verdict = survivorship_audit(coverage(listings=False, delistings=None))
    assert "listings" in " ".join(verdict.missing)
    assert "delistings" in " ".join(verdict.undetermined)


def test_no_coverage_field_may_default() -> None:
    """A defaulted field is *"we did not check"* silently reading as *"covered"*.

    This module's whole argument is that the two are different — reported apart, because one is
    an archive to obtain and the other a check to run. A default undoes that at construction
    time instead of in the audit, which is worse: the audit never sees the omission, so the
    verdict is confidently wrong rather than undetermined.

    Asserted over every field rather than the one that happens to be last, so a sixth
    requirement cannot arrive with a permissive default the way a fifth could.
    """
    for field in dataclasses.fields(ArchivalCoverage):
        assert field.default is dataclasses.MISSING, f"{field.name} defaults to {field.default!r}"
        assert field.default_factory is dataclasses.MISSING, f"{field.name} has a default factory"


def test_an_omitted_coverage_is_refused_at_construction() -> None:
    """The same property from the caller's side: you cannot forget one quietly."""
    with pytest.raises(TypeError, match="daily_eligibility"):
        ArchivalCoverage(  # type: ignore[call-arg]
            listings=True, delistings=True, token_changes=True, corporate_actions=True
        )
