"""Canonicalization and content-addressed identity  [C-ID-01].

Every config, artifact and trial identity in pips resolves to a SHA-256 over a
*canonical* byte encoding: sorted keys, normalized floats, no ambiguity. The same
logical object must hash identically on every machine and every run (constitution
rule 1: determinism).

Float policy ([C-NUM-01]): NaN and infinities cannot cross a schema boundary, so they
cannot be hashed either -- they raise. Negative zero normalizes to zero, so ``-0.0``
and ``0.0`` are the same object.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any, Final

__all__ = ["ShortId", "canonical_bytes", "canonicalize", "content_hash", "short_id"]

ShortId = str
"""First 16 hex characters of a content hash -- the human-facing form."""

_SHORT_ID_LEN: Final = 16


def _canon_float(value: float) -> str:
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"non-finite float cannot be canonicalized: {value!r}")
    if value == 0.0:
        return "0.0"  # collapses -0.0
    return repr(value)  # shortest round-tripping decimal form


def _canon_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def canonicalize(obj: Any) -> str:
    """Render ``obj`` as a deterministic canonical string.

    Accepts ``None``, ``bool``, ``int``, ``float``, ``str``, sequences and string-keyed
    mappings. Anything else raises -- an object with no defined ordering (a ``set``) or
    no defined encoding has no place in an identity hash.
    """
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return _canon_float(obj)
    if isinstance(obj, str):
        return _canon_str(obj)
    if isinstance(obj, Mapping):
        keys = list(obj.keys())
        if any(not isinstance(k, str) for k in keys):
            raise TypeError("only string-keyed mappings can be canonicalized")
        items = ",".join(f"{_canon_str(k)}:{canonicalize(obj[k])}" for k in sorted(keys))
        return "{" + items + "}"
    if isinstance(obj, Sequence) and not isinstance(obj, str | bytes):
        return "[" + ",".join(canonicalize(v) for v in obj) + "]"
    raise TypeError(f"type {type(obj).__name__!r} is not canonicalizable")


def canonical_bytes(obj: Any) -> bytes:
    """UTF-8 bytes of :func:`canonicalize` -- the exact preimage that gets hashed."""
    return canonicalize(obj).encode("utf-8")


def content_hash(obj: Any) -> str:
    """Full 64-hex SHA-256 of the canonical encoding of ``obj``."""
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def short_id(full_hash: str) -> ShortId:
    """First 16 hex characters of a full hash, validated."""
    if len(full_hash) != 64 or not all(c in "0123456789abcdef" for c in full_hash):
        raise ValueError(f"not a lowercase 64-hex sha256: {full_hash!r}")
    return full_hash[:_SHORT_ID_LEN]
