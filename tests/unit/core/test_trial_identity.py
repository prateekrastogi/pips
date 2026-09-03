"""Trial identity and the result cache [C-ID-01] (§3.1).

§3.1 says trial identity hashes **all** of a named list. "All" is the load-bearing word, and
it is the part that rots: someone adds a field to the model six milestones from now and the
hash quietly stops distinguishing it, so two different trials collide and the second silently
returns the first one's cached result. The completeness test below iterates the model's own
fields, so a field that is added but not hashed fails immediately.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pips.core.trial import TrialCache, TrialIdentity, current_runtime_versions

BASE: dict[str, Any] = {
    "code_commit": "7b8e32e0a1b2c3d4e5f60718293a4b5c6d7e8f90",
    "data_snapshot_root": "a" * 64,
    "instrument_master_hash": "b" * 64,
    "corporate_action_hash": "c" * 64,
    "calendar_hash": "d" * 64,
    "pipeline_dag_hash": "e" * 64,
    "universe_policy_hash": "f" * 64,
    "split_definition_hash": "0" * 64,
    "cost_model_hash": "1" * 64,
    "parameters": {"lookback": 20, "k": 0.5},
    "fill_tier": "F1",
    "capital_tier": "2L",
    "seed": 7,
    "runtime_versions": {"python": "3.12.7", "polars": "1.9.0"},
}


def identity(**over: Any) -> TrialIdentity:
    return TrialIdentity.model_validate({**BASE, **over})


def test_the_same_inputs_give_the_same_id() -> None:
    assert identity().trial_id() == identity().trial_id()


def test_the_id_is_a_full_sha256_with_a_16_hex_short_form() -> None:
    ident = identity()
    assert len(ident.trial_id()) == 64
    assert ident.short_id() == ident.trial_id()[:16]


def test_field_declaration_order_does_not_affect_the_id() -> None:
    reordered = dict(reversed(list(BASE.items())))
    assert TrialIdentity.model_validate(reordered).trial_id() == identity().trial_id()


@pytest.mark.parametrize("field_name", sorted(TrialIdentity.model_fields))
def test_every_field_changes_the_trial_id(field_name: str) -> None:
    """The completeness guard. Every declared field must be part of the identity.

    Parametrised over the model's OWN fields, so adding a field without hashing it fails
    here rather than years later as a silent cache collision between distinct trials.
    """
    current = BASE[field_name]
    if isinstance(current, dict):
        # A string probe: runtime_versions is dict[str, str] under strict validation, so an
        # int probe would fail construction instead of testing the hash.
        mutated: Any = {**current, "__probe__": "1"}
    elif isinstance(current, int) and not isinstance(current, bool):
        mutated = current + 1
    else:
        mutated = f"{current}-probe"
    assert identity(**{field_name: mutated}).trial_id() != identity().trial_id(), (
        f"{field_name!r} does not change the trial id — §3.1 requires ALL fields to be hashed"
    )


def test_capital_tier_changes_the_id() -> None:
    # Called out explicitly in §3.1, and the one people forget: the same strategy at a
    # different capital tier faces different costs and is a different trial.
    assert identity(capital_tier="10L").trial_id() != identity(capital_tier="2L").trial_id()


def test_fill_tier_changes_the_id() -> None:
    # Cross-tier comparisons are refused by report code (§3.8); they must not collide here.
    assert identity(fill_tier="F2").trial_id() != identity(fill_tier="F1").trial_id()


def test_a_non_finite_parameter_is_refused() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        identity(parameters={"k": math.inf}).trial_id()


def test_a_missing_field_is_refused_at_construction() -> None:
    incomplete = {k: v for k, v in BASE.items() if k != "seed"}
    with pytest.raises(ValueError, match="seed"):
        TrialIdentity.model_validate(incomplete)


def test_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValueError):
        identity(surprise="value")


def test_runtime_versions_are_captured_from_the_live_interpreter() -> None:
    versions = current_runtime_versions()
    assert versions["python"].count(".") >= 2
    assert "polars" in versions


# ---------------------------------------------------------------- the cache -----------


def test_rerunning_an_existing_hash_returns_the_cached_result(tmp_path: Path) -> None:
    # §3.1: "Re-running an existing hash returns the cached result."
    cache = TrialCache(tmp_path)
    calls: list[int] = []

    def compute() -> dict[str, Any]:
        calls.append(1)
        return {"sharpe": 1.25}

    first, cached_first = cache.run_or_load(identity(), compute)
    second, cached_second = cache.run_or_load(identity(), compute)

    assert first == second == {"sharpe": 1.25}
    assert cached_first is False and cached_second is True
    assert len(calls) == 1, "the second run must not recompute"


def test_a_different_identity_recomputes(tmp_path: Path) -> None:
    cache = TrialCache(tmp_path)
    calls: list[str] = []

    def make(tag: str) -> Callable[[], dict[str, Any]]:
        def compute() -> dict[str, Any]:
            calls.append(tag)
            return {"tag": tag}

        return compute

    cache.run_or_load(identity(seed=1), make("a"))
    cache.run_or_load(identity(seed=2), make("b"))
    assert calls == ["a", "b"]


def test_the_cache_entry_is_named_by_the_trial_id(tmp_path: Path) -> None:
    cache = TrialCache(tmp_path)
    ident = identity()
    cache.run_or_load(ident, lambda: {"x": 1})
    assert cache.path_for(ident.trial_id()).exists()
    assert ident.trial_id() in str(cache.path_for(ident.trial_id()))


def test_the_cache_round_trips_the_result_exactly(tmp_path: Path) -> None:
    cache = TrialCache(tmp_path)
    payload = {"sharpe": 1.25, "n_trades": 412, "by_day": [0.1, -0.2], "note": "a\nb"}
    cache.run_or_load(identity(), lambda: payload)
    loaded = cache.get(identity().trial_id())
    assert loaded == payload


def test_a_cache_miss_reports_none(tmp_path: Path) -> None:
    assert TrialCache(tmp_path).get("f" * 64) is None


def test_the_cache_records_the_identity_beside_the_result(tmp_path: Path) -> None:
    # A result without a resolvable identity is not evidence (constitution rule 3). The
    # entry must be able to say what produced it, not just what came out.
    cache = TrialCache(tmp_path)
    ident = identity()
    cache.run_or_load(ident, lambda: {"x": 1})
    entry = cache.entry_for(ident.trial_id())
    assert entry is not None
    assert entry["identity"]["capital_tier"] == "2L"
    assert entry["trial_id"] == ident.trial_id()


# --------------------------------------------------------- found by mutation sweep ---


def test_a_cache_entry_is_the_same_bytes_whatever_order_it_was_built_in(tmp_path: Path) -> None:
    """The comment beside the write says why: `make determinism` would otherwise fail on the
    cache rather than on the maths.

    A result dict assembled in a different key order is the same result, and must be the same
    file. Without `sort_keys` the bytes follow insertion order — stable within one process and
    not across two, which is exactly the class the determinism gate was just widened to catch
    and which it would still miss here, because the fixture pipeline does not touch this cache.
    """
    cache = TrialCache(tmp_path / "cache")
    trial = identity()

    cache.put(trial, {"sharpe": 1.5, "trades": 42, "alpha": "A01"})
    first = cache.path_for(trial.trial_id()).read_bytes()

    cache.put(trial, {"alpha": "A01", "trades": 42, "sharpe": 1.5})
    second = cache.path_for(trial.trial_id()).read_bytes()

    assert first == second


def test_cache_entries_are_sharded_by_prefix(tmp_path: Path) -> None:
    """Operational rather than correctness, and worth saying which.

    A flat directory holding one file per trial is still correct — every read finds what every
    write put there. What it is not is workable at campaign scale: the 3y x U300 run enumerates
    234,900 symbol-days, and search trials outnumber that. Two hex characters split them across
    256 directories for the cost of one slice.
    """
    cache = TrialCache(tmp_path / "cache")
    trial = identity()
    trial_id = cache.put(trial, {"ok": True})

    path = cache.path_for(trial_id)
    assert path.parent.name == trial_id[:2]
    assert path.parent.parent == tmp_path / "cache"
    assert cache.get(trial_id) == {"ok": True}
