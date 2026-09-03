"""`PipsConfig`, the contract every model in the project inherits.

Three words in one `ConfigDict` decide how safe every config, every record and every bundle
field is — `extra="forbid"`, `frozen=True`, `strict=True` — and the module had no test file of
its own. Only one of the three was pinned anywhere, by a test in `test_trial_identity.py` about
something else, which is why removing the other two changed nothing.

The properties here are load-bearing for things stated elsewhere. `PitStore.all_records` explains
that it uses `model_validate_json` rather than `model_validate(json.loads(...))` *because*
`PipsConfig` is strict and strict python-mode validation rejects a `str` where a `date` is
declared. That reasoning is only true while `strict=True` is there.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from pips.core.config import (
    DecimalFromNumber,
    DecimalFromStr,
    PipsConfig,
    config_hash,
    load_yaml,
)


class Sample(PipsConfig):
    name: str
    count: int
    ratio: DecimalFromStr = Decimal("0")
    stress: DecimalFromNumber = Decimal("0")


def test_an_unknown_field_is_refused() -> None:
    """`extra="forbid"`. A typo'd key that lands quietly is a setting nobody applied.

    Pinned here as well as in `test_trial_identity.py`, because that file is about trial
    identity and this property belongs to every model — a reader looking for the base class's
    guarantees should not have to know where it happens to be asserted.
    """
    with pytest.raises(ValidationError, match="Extra inputs"):
        Sample(name="a", count=1, tyop=2)  # type: ignore[call-arg]


def test_a_validated_model_cannot_be_mutated() -> None:
    """`frozen=True`, and the content hash is the reason.

    A config's identity IS its content hash — snapshots are pinned to it and runs are
    reproduced from it. A model mutated after validation still reports the hash it was
    validated under until someone recomputes it, so the pin points at bytes that no longer
    exist.
    """
    config = Sample(name="a", count=1)
    with pytest.raises(ValidationError, match="frozen"):
        config.count = 2


def test_validation_is_strict_and_does_not_coerce() -> None:
    """`strict=True`. A quoted number is not a number.

    Lax pydantic turns `"1"` into `1` and `1` into `1.0` on the way in, which sounds
    convenient and means a config file that says one thing produces a model that says another.
    `PitStore` relies on this exact behaviour to reject a `str` where a `date` is declared,
    and says so in a comment that is only true while this holds.
    """
    with pytest.raises(ValidationError):
        Sample(name="a", count="1")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Sample(name=5, count=1)  # type: ignore[arg-type]


def test_a_decimal_from_a_string_is_exact() -> None:
    """Via the string, never the binary float, so 1.1 is 1.1 and not 1.100000000000000088."""
    assert Sample(name="a", count=1, ratio="1.1").ratio == Decimal("1.1")  # type: ignore[arg-type]
    assert Sample(name="a", count=1, stress=1.1).stress == Decimal("1.1")  # type: ignore[arg-type]
    # RUF032 is right in general and wrong here: the binary expansion is the thing being
    # excluded, so it has to appear.
    assert Sample(name="a", count=1, stress=1.1).stress != Decimal(1.1)  # type: ignore[arg-type]  # noqa: RUF032


def test_yaml_is_loaded_without_custom_tags(tmp_path: Path) -> None:
    """`safe_load`. "No custom tags, ever" is the docstring, and this is what enforces it.

    An unsafe loader constructs arbitrary Python objects named in the document, so a config
    file becomes code. Configs here are read from a repository and a VM, which is exactly the
    threat model where "it is our own file" stops being an argument.
    """
    document = tmp_path / "c.yaml"
    document.write_text("value: !!python/object/apply:os.system ['echo pwned']\n")

    with pytest.raises(Exception, match="python/object"):
        load_yaml(document)


def test_the_content_hash_is_over_the_json_form_and_is_stable() -> None:
    """Two equal configs hash alike; one different field moves it.

    Taken over the JSON-mode dump so a `Decimal` or a `date` hashes as the text it serialises
    to rather than as a Python object's repr — the same bytes a reader of the file would see.
    """
    one = Sample(name="a", count=1, ratio="1.1")  # type: ignore[arg-type]
    same = Sample(name="a", count=1, ratio="1.1")  # type: ignore[arg-type]
    other = Sample(name="a", count=2, ratio="1.1")  # type: ignore[arg-type]

    assert one.content_hash() == same.content_hash()
    assert one.content_hash() != other.content_hash()
    assert one.content_hash() == config_hash(one.model_dump(mode="json"))


def test_the_short_id_is_derived_from_the_content_hash() -> None:
    """Not from the object's repr, which carries field order and class name and is not the
    identity anything is pinned to."""
    config = Sample(name="a", count=1)
    assert config.content_hash().startswith(config.short_id())
