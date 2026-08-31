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
