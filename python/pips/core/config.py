"""Config loading and the config hash  [C-ID-01].

A config is YAML, validated by a pydantic model, then canonicalized and hashed. The
hash -- not the file path, not the mtime -- is the config's identity, and it appears on
every log line, registry row, artifact and bundle built from it.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict

from pips.core.ids import ShortId, content_hash, short_id

__all__ = [
    "DecimalFromNumber",
    "DecimalFromStr",
    "PipsConfig",
    "config_hash",
    "config_short_id",
    "load_config",
    "load_yaml",
]


def _decimal(value: object) -> object:
    return Decimal(value) if isinstance(value, str) else value


def _decimal_from_number(value: object) -> object:
    """Accept a str, int or float and produce an exact Decimal.

    Via ``str()`` for floats, so ``1.5`` becomes ``Decimal("1.5")`` rather than the binary
    expansion. Used where the SOURCE DOCUMENT writes numbers unquoted and we must accept its
    form rather than making the document fit the schema -- the reference's Appendix B
    manifest writes ``stress: [1.0, 1.5, 2.0]``, and a schema that rejected it would be
    testing itself instead of the document.
    """
    if isinstance(value, str):
        return Decimal(value)
    if isinstance(value, bool):
        raise TypeError("a bool is not a number here")
    if isinstance(value, int | float):
        return Decimal(str(value))
    return value


DecimalFromStr = Annotated[Decimal, BeforeValidator(_decimal)]
"""A ``Decimal`` that accepts a quoted YAML string.

Rates are quoted in YAML deliberately: a YAML float is binary and already lossy before it
reaches us, so ``0.0000297`` would arrive as something that is not ``0.0000297`` and every
golden would miss by a hair nobody could explain. :class:`PipsConfig` is strict, so the
string form needs an explicit conversion -- and it must attach to the FIELD, not run as a
wildcard validator, or it tries to parse prose fields like ``source`` as numbers. That was
a real failure, not a hypothetical one.
"""

DecimalFromNumber = Annotated[Decimal, BeforeValidator(_decimal_from_number)]
"""A ``Decimal`` that also accepts an unquoted YAML number. See :func:`_decimal_from_number`."""


class PipsConfig(BaseModel):
    """Base for every pips config model: strict, frozen, hashable by content."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def content_hash(self) -> str:
        return config_hash(self.model_dump(mode="json"))

    def short_id(self) -> ShortId:
        return short_id(self.content_hash())


def load_yaml(path: Path) -> Any:
    """Load a YAML document with the safe loader. No custom tags, ever."""
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_config[T: PipsConfig](path: Path, model: type[T]) -> T:
    """Load and validate a YAML config into ``model``."""
    return model.model_validate(load_yaml(path))


def config_hash(payload: Any) -> str:
    """Full SHA-256 over the canonical encoding of a config payload."""
    return content_hash(payload)


def config_short_id(payload: Any) -> ShortId:
    """16-hex short id of a config payload."""
    return short_id(config_hash(payload))
