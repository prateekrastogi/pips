"""Binding falsifiers to the checks that evaluate them  [C-SPEC-01] (§3.2, rule 5, §6 M16).

`alphas/spec.py` has carried this note since M12, after its text validator was twice wrong:

    The real enforcement is elsewhere and is named here so nobody mistakes this for it: human
    review at pre-registration, and M16's stress battery actually APPLYING each falsifier. When
    that battery exists, the honest strengthening is to require each falsifier to name the
    check that evaluates it — a structural binding, not a parse of English.

The battery exists now, so this is that binding. Three rules, and the third is the one that
makes it worth having:

**A named check must exist.** Not "be plausible" — resolve. Each id maps to a module that must
import and, for a stress case, to a case name the battery actually declares. A falsifier naming
a check that does not exist is worse than one naming nothing, because it claims coverage.

**A named falsifier must be one that was pre-registered.** Binding a check to text that is not
in the spec's own `falsifiers` list is annotating a rejection condition nobody registered.

**An unbound falsifier is REPORTED, not tolerated in silence.** Most falsifiers in the
catalogue cannot be bound today — the checks they need do not exist. Inventing bindings to make
the report look complete would be the exact failure this replaces: prose that reads as
enforcement. So the report counts them, and the count is expected to be large.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pips.alphas.spec import AlphaSpec, load_alpha_spec
from pips.validation.falsifier_binding import (
    CHECK_REGISTRY,
    coverage_report,
    resolve_check,
    unbound_falsifiers,
)

SPEC_DIR = Path("config/search_spaces")


def specs() -> list[AlphaSpec]:
    return sorted((load_alpha_spec(p) for p in SPEC_DIR.glob("A*.yaml")), key=lambda s: s.id)


# ------------------------------------------------- the checks must be real --------------


def test_every_registered_check_resolves_to_something_that_exists() -> None:
    """The structural half. A registry of names is a wish list until the names resolve.

    Each id maps to an importable module, and every id that claims to be a stress case must be
    one the battery actually declares. Without this the binding is the same prose problem in
    a different file.
    """
    assert CHECK_REGISTRY, "an empty registry binds nothing"
    for check_id in CHECK_REGISTRY:
        resolve_check(check_id)  # raises if it does not exist


def test_a_check_id_that_does_not_resolve_is_refused() -> None:
    with pytest.raises(LookupError, match="unknown check"):
        resolve_check("cost-x99")


def test_a_stress_case_id_must_be_one_the_battery_declares() -> None:
    from pips.validation.stress import default_cases

    declared = {c.name for c in default_cases()}
    for check_id, target in CHECK_REGISTRY.items():
        if target == "pips.validation.stress":
            assert check_id in declared, (
                f"{check_id} is registered as a stress case but the battery does not declare "
                "it — the binding would name a case that never runs"
            )


# ------------------------------------------------- the spec side ------------------------


def test_a_binding_to_an_unregistered_falsifier_is_refused() -> None:
    payload = load_alpha_spec(SPEC_DIR / "A07_opening_range_breakout.yaml").model_dump()
    payload["falsifier_checks"] = [
        {"falsifier": "Reject if the moon is full", "check": "cost-x1.5"}
    ]
    with pytest.raises(ValueError, match="not one of the declared falsifiers"):
        AlphaSpec.model_validate(payload)


def test_a_binding_to_an_unknown_check_is_refused() -> None:
    spec = load_alpha_spec(SPEC_DIR / "A07_opening_range_breakout.yaml")
    payload = spec.model_dump()
    payload["falsifier_checks"] = [{"falsifier": spec.falsifiers[0], "check": "not-a-real-check"}]
    with pytest.raises(ValueError, match="unknown check"):
        AlphaSpec.model_validate(payload)


def test_a07_binds_its_plateau_falsifier_to_plateau_selection() -> None:
    """The one binding that is unambiguous.

    A07: *"Reject if small changes to range_end or buffer reverse the result."* That is
    precisely what plateau-centroid selection tests, and the check exists.
    """
    a07 = next(s for s in specs() if s.id == "A07")
    bound = {b.falsifier: b.check for b in a07.falsifier_checks}
    assert any("range_end" in text for text in bound)
    assert "plateau-centroid" in bound.values()


# ------------------------------------------------- the honest report --------------------


def test_the_coverage_report_counts_unbound_falsifiers_rather_than_hiding_them() -> None:
    """Most falsifiers cannot be bound today, and the report must say so.

    Inventing bindings to make this look complete would be the exact failure this replaces:
    prose that reads as enforcement. A large unbound count is the correct answer right now.
    """
    report = coverage_report(specs())
    assert report.total_falsifiers > 20
    assert report.bound > 0, "at least one falsifier must be genuinely bound"
    assert report.unbound > 0, (
        "a report claiming full coverage today would be false — the checks most falsifiers "
        "need do not exist yet"
    )
    assert report.bound + report.unbound == report.total_falsifiers


def test_unbound_falsifiers_are_named_not_just_counted() -> None:
    # A count tells you there is work; the names tell you what work. A report that only
    # counts gets read as a score.
    # A04, not A12: A12's three falsifiers are all bound now (family-wise correction,
    # leave-day-out, era-stability), so it is no longer an example of anything unbound. That
    # a spec graduating out of this test is what breaks it is the right failure mode.
    a04 = next(s for s in specs() if s.id == "A04")
    unbound = unbound_falsifiers(a04)
    assert unbound
    assert all(text in a04.falsifiers for text in unbound)


def test_a_deferred_falsifier_is_not_counted_as_bound() -> None:
    """A06 defers its event-metadata falsifier: pre-registered, and not yet evaluable.

    Deferred and bound are opposite states. Counting a deferred condition as covered would
    let the report improve by declaring things unrunnable.
    """
    a06 = next(s for s in specs() if s.id == "A06")
    assert a06.falsifiers_deferred
    bound = {b.falsifier for b in a06.falsifier_checks}
    for deferred in a06.falsifiers_deferred:
        head = deferred.split(" — needs ")[0].strip()
        assert not any(head in b for b in bound), (
            "a deferred falsifier must not also be reported as bound"
        )


def test_the_report_renders_for_a_human() -> None:
    text = coverage_report(specs()).describe()
    assert "unbound" in text
    assert "A01" in text, "a spec with unbound falsifiers must be listed with its names"


def test_a_fully_bound_spec_does_not_appear_in_the_unbound_listing() -> None:
    """A07's three falsifiers are all bound, so it is absent from the report — correctly.

    My first version asserted A07 WAS in the text, on the assumption every spec would have
    something outstanding. It does not, and the report listing only what is still open is the
    right shape: a reader scans for work, not for a roll call.
    """
    a07 = next(s for s in specs() if s.id == "A07")
    assert unbound_falsifiers(a07) == ()
    assert "A07" not in coverage_report(specs()).describe()


def test_a_registered_check_whose_module_does_not_exist_is_caught() -> None:
    """The structural half, pinned. Without this the registry is a dictionary of strings.

    `test_every_registered_check_resolves_to_something_that_exists` walks the real registry,
    where every module exists — so it passes whether or not `resolve_check` actually imports
    anything. A mutation removing the import killed nothing, which means the difference
    between "this check exists" and "this name is in a dict I wrote" was untested. That
    difference is the whole premise of the module.

    Adding an entry that points at nothing is the only way to observe it.
    """
    from unittest.mock import patch

    with (
        patch.dict(CHECK_REGISTRY, {"phantom": "pips.validation.no_such_module"}),
        pytest.raises(ModuleNotFoundError),
    ):
        resolve_check("phantom")


def test_a_spec_naming_a_check_with_a_missing_module_is_refused() -> None:
    # And the same through the spec boundary, since that is where it would actually bite.
    from unittest.mock import patch

    spec = load_alpha_spec(SPEC_DIR / "A07_opening_range_breakout.yaml")
    payload = spec.model_dump()
    payload["falsifier_checks"] = [{"falsifier": spec.falsifiers[0], "check": "phantom"}]
    with (
        patch.dict(CHECK_REGISTRY, {"phantom": "pips.validation.no_such_module"}),
        pytest.raises(ModuleNotFoundError),
    ):
        AlphaSpec.model_validate(payload)
