"""Property tests for the identity and money primitives."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from pips.core.ids import canonicalize, content_hash
from pips.core.money import notional_paise, round_to_tick

_json_like: st.SearchStrategy[Any] = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.text()
    | st.floats(allow_nan=False, allow_infinity=False),
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(st.text(), children, max_size=5)
    ),
    max_leaves=20,
)


@given(_json_like)
def test_canonicalization_is_a_function_of_value_alone(obj: Any) -> None:
    assert content_hash(obj) == content_hash(obj)


@given(st.dictionaries(st.text(), st.integers(), max_size=8))
def test_dict_hash_ignores_insertion_order(mapping: dict[str, int]) -> None:
    reversed_mapping = dict(reversed(list(mapping.items())))
    assert content_hash(mapping) == content_hash(reversed_mapping)


@given(_json_like)
def test_canonical_form_round_trips_through_hashing(obj: Any) -> None:
    assert canonicalize(obj) == canonicalize(obj)


@given(st.integers(min_value=1, max_value=10**9), st.integers(min_value=1, max_value=100))
def test_rounding_to_tick_lands_on_a_tick(price: int, tick: int) -> None:
    rounded = round_to_tick(price, tick)
    assert rounded % tick == 0
    assert abs(rounded - price) <= tick


@given(
    st.integers(min_value=-(10**9), max_value=10**9),
    st.integers(min_value=-(10**6), max_value=10**6),
)
def test_notional_is_exactly_the_integer_product(price: int, qty: int) -> None:
    assert notional_paise(price, qty) == Decimal(price) * Decimal(qty)
