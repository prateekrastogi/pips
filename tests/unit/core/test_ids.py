"""Canonicalization and identity [C-ID-01]."""

from __future__ import annotations

import math

import pytest

from pips.core.ids import canonicalize, content_hash, short_id


def test_key_order_does_not_change_the_hash() -> None:
    assert content_hash({"b": 1, "a": 2}) == content_hash({"a": 2, "b": 1})


def test_nested_key_order_does_not_change_the_hash() -> None:
    left = {"outer": {"z": [1, {"b": 2, "a": 3}], "y": 0}}
    right = {"outer": {"y": 0, "z": [1, {"a": 3, "b": 2}]}}
    assert content_hash(left) == content_hash(right)


def test_list_order_does_change_the_hash() -> None:
    assert content_hash([1, 2]) != content_hash([2, 1])


def test_negative_zero_normalizes() -> None:
    assert canonicalize(-0.0) == canonicalize(0.0) == "0.0"


def test_bool_is_not_int() -> None:
    assert canonicalize(True) == "true"
    assert canonicalize(1) == "1"
    assert content_hash(True) != content_hash(1)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_floats_are_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        canonicalize(bad)


def test_unorderable_containers_are_refused() -> None:
    with pytest.raises(TypeError):
        canonicalize({1, 2, 3})


def test_non_string_keys_are_refused() -> None:
    with pytest.raises(TypeError, match="string-keyed"):
        canonicalize({1: "a"})


def test_canonical_encoding_is_pinned() -> None:
    # The canonical form is the hash preimage. Pinned literally, because changing it
    # silently re-points every historical config hash in the registry -- that is an
    # ADR plus a migration, never a quiet edit.
    payload = {"seed": 7, "universe": "U100"}
    assert canonicalize(payload) == '{"seed":7,"universe":"U100"}'
    assert content_hash(payload) == (
        "72aec30e0c4b26dfec9145527c5ccb8f435b26b581457b9d866af3953571326d"
    )


def test_short_id_validates_its_input() -> None:
    full = content_hash({"a": 1})
    assert short_id(full) == full[:16]
    with pytest.raises(ValueError, match="64-hex"):
        short_id("deadbeef")


# --------------------------------------------------------- found by mutation sweep ---


def test_a_value_cannot_forge_the_structure_around_it() -> None:
    """The collision this escaping exists to prevent, written out.

    Without quote escaping, one field whose value carries `","role":"admin` encodes to exactly
    the same bytes as two genuine fields — verified by construction, not argued: both render
    `{"name":"x","role":"admin"}` and hash alike. Every identity in this project rests on this
    function: snapshot roots `[C-DATA-02]`, dossier hashes, bundle content hashes. Two different
    objects sharing one identity is the worst failure an identity function has, and it is
    reachable from any string a config or a vendor supplies.
    """
    forged = {"name": 'x","role":"admin'}
    genuine = {"name": "x", "role": "admin"}

    assert canonicalize(forged) != canonicalize(genuine)
    assert content_hash(forged) != content_hash(genuine)


@pytest.mark.parametrize(
    "values",
    [
        ('x","y":"z', "x", "x\\", '"'),  # quote and backslash forgeries
        ("a\nb", "a\\nb", "ab"),  # a real newline against its escape written out
        ("", '""', "\\"),  # empty, quoted-empty, lone backslash
    ],
)
def test_distinct_strings_stay_distinct_once_encoded(values: tuple[str, ...]) -> None:
    """Injectivity on adversarial input, which is the property all three escapes serve.

    Stated as a set rather than one pair per escape: what matters is that no two different
    strings ever meet, and the individual replacements are how that is achieved rather than
    what is promised.
    """
    encoded = [canonicalize(v) for v in values]
    assert len(set(encoded)) == len(values), dict(zip(values, encoded, strict=True))


def test_bytes_are_refused_rather_than_iterated_as_numbers() -> None:
    """`bytes` is a `Sequence`, so without the exclusion it encodes as a list of ints —
    and then `b"ab"` and `[97, 98]` are the same identity."""
    with pytest.raises(TypeError, match="canonicaliz"):
        canonicalize(b"ab")
    assert canonicalize([97, 98]) == "[97,98]"


def test_floats_keep_every_digit_that_distinguishes_them() -> None:
    """`repr`, the shortest round-tripping form — not a rounded one.

    Rounding to six places makes `0.1 + 0.2` and `0.3` one value. They are not one value, and a
    hash that says they are will report two different cost models, two different thresholds or
    two different snapshots as the same thing.
    """
    assert 0.1 + 0.2 != 0.3
    assert content_hash(0.1 + 0.2) != content_hash(0.3)
    assert canonicalize(1e-9) != canonicalize(2e-9)


def test_a_short_id_refuses_a_string_that_is_not_a_hash() -> None:
    """Length alone is not enough: 64 characters of anything is not a digest.

    The id is what a human quotes and a store is searched by, so accepting a 64-character
    non-hash records something that looks like provenance and matches nothing.
    """
    with pytest.raises(ValueError, match="64-hex"):
        short_id("Z" * 64)
    with pytest.raises(ValueError, match="64-hex"):
        short_id("A" * 64)  # uppercase hex is not the lowercase form stores are keyed by
    assert short_id("a" * 64) == "a" * 16


def test_the_canonical_form_of_anything_is_one_line() -> None:
    """The newline escape is not about collisions, and pretending otherwise would mis-state it.

    A raw newline is not a delimiter in this grammar, so leaving it unescaped keeps the encoding
    injective — the property the quote and backslash escapes exist for. What it breaks is that
    the canonical form is a single line, which is what lets it sit in a JSONL record, a log line
    or a one-line diff without the reader having to guess where a value ended.
    """
    encoded = canonicalize({"note": "first\nsecond", "n": 1})

    assert "\n" not in encoded
    assert encoded.count("\\n") == 1
