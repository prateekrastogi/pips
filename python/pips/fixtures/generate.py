"""Seeded smoke-fixture generator (§4).

Two symbols x five days of synthetic close-labelled 1-minute bars, plus one day of
1-second bars, so the whole funnel is runnable with zero API access. The generator is
seeded with Python's Mersenne Twister (stable across CPython versions) and emits
integer paise only -- no float ever reaches a fixture file.

Regenerating with the same seed must reproduce byte-identical files; ``make determinism``
depends on exactly that.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from pips.core.ids import content_hash
from pips.core.time import NS_PER_MINUTE, NS_PER_SECOND, bar_label_ns, ts_from_iso

__all__ = ["FixtureSpec", "Manifest", "generate", "main"]

SESSION_OPEN = "09:15:00"
SESSION_MINUTES = 375  # 09:15 -> 15:30 continuous session
DEFAULT_SEED = 20260831


class Manifest(TypedDict):
    """What ``make determinism`` compares: per-file hashes under one root hash."""

    spec: dict[str, object]
    spec_hash: str
    files: dict[str, str]
    manifest_hash: str


@dataclass(frozen=True)
class FixtureSpec:
    """Everything that determines the fixture bytes -- hashed into the manifest."""

    symbols: tuple[str, ...] = ("SMOKEA", "SMOKEB")
    days: tuple[str, ...] = (
        "2026-06-01",
        "2026-06-02",
        "2026-06-03",
        "2026-06-04",
        "2026-06-05",
    )
    seed: int = DEFAULT_SEED
    start_price_paise: int = 250_000  # ₹2,500.00
    tick_paise: int = 5
    second_bar_day: str = "2026-06-05"
    second_bar_symbol: str = "SMOKEA"
    session_minutes: int = SESSION_MINUTES
    """Bars in a session. 375 is the real NSE day (09:15 -> 15:30).

    Part of the spec, so part of the manifest hash: two panels differing only in session length
    are different data and must not share an identity.
    """

    def payload(self) -> dict[str, object]:
        return {
            "symbols": list(self.symbols),
            "days": list(self.days),
            "seed": self.seed,
            "start_price_paise": self.start_price_paise,
            "tick_paise": self.tick_paise,
            "second_bar_day": self.second_bar_day,
            "second_bar_symbol": self.second_bar_symbol,
            "session_minutes": self.session_minutes,
        }


WIDE_SPEC = FixtureSpec(
    # Eight names instead of two. `make s5-smoke` runs seven families over a two-symbol panel,
    # so every alpha trades the same two names, their PnL streams overlap by construction, and
    # the pairwise gate collapses them almost regardless of merit. A03 (cross-sectional
    # reversal) and A04 (residual reversion) rank a cross-section of two, which is a tie.
    #
    # SESSIONS ARE DELIBERATELY UNCHANGED. The as-of loop iterates TIMESTAMPS, so widening the
    # cross-section leaves the number of decision points -- and the search runtime -- alone.
    # Adding sessions multiplies both. Five already give A05 a prior close and A07 an opening
    # range four times over; A12 needs sixty and is a separate decision.
    symbols=(
        "WIDEA",
        "WIDEB",
        "WIDEC",
        "WIDED",
        "WIDEE",
        "WIDEF",
        "WIDEG",
        "WIDEH",
    ),
    second_bar_symbol="WIDEA",
)
"""A broader cross-section for `make s5-smoke`, generated on demand rather than committed.

Four times the bars of the default, and the spec hash makes it reproducible from the seed
(rule 1), so storing the bytes buys nothing.
"""


def _stream(
    spec: FixtureSpec, symbol: str, day: str, interval_ns: int, count: int
) -> list[dict[str, int | str]]:
    """One session of bars for one symbol as an integer-paise random walk."""
    rng = random.Random(content_hash([spec.seed, symbol, day, interval_ns]))
    session_open = ts_from_iso(f"{day}T{SESSION_OPEN}")
    price = spec.start_price_paise
    bars: list[dict[str, int | str]] = []
    for i in range(count):
        label = bar_label_ns(session_open + (i + 1) * interval_ns, interval_ns, session_open)
        open_p = price
        moves = [rng.randint(-4, 4) * spec.tick_paise for _ in range(4)]
        path = [open_p]
        for move in moves:
            path.append(max(spec.tick_paise, path[-1] + move))
        close_p = path[-1]
        bars.append(
            {
                "symbol": symbol,
                "close_ts_ns": int(label),
                "open_paise": open_p,
                "high_paise": max(path),
                "low_paise": min(path),
                "close_paise": close_p,
                "volume": rng.randint(100, 10_000),
            }
        )
        price = close_p
    return bars


def _write(path: Path, bars: list[dict[str, int | str]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(bars, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return content_hash(text)


def generate(out_dir: Path, spec: FixtureSpec | None = None) -> Manifest:
    """Write every fixture file under ``out_dir`` and return the manifest."""
    spec = spec or FixtureSpec()
    files: dict[str, str] = {}

    for symbol in spec.symbols:
        for day in spec.days:
            rel = f"bars/1m/{symbol}_{day}.json"
            files[rel] = _write(
                out_dir / rel, _stream(spec, symbol, day, NS_PER_MINUTE, spec.session_minutes)
            )

    rel = f"bars/1s/{spec.second_bar_symbol}_{spec.second_bar_day}.json"
    files[rel] = _write(
        out_dir / rel,
        _stream(
            spec,
            spec.second_bar_symbol,
            spec.second_bar_day,
            NS_PER_SECOND,
            spec.session_minutes * 60,
        ),
    )

    body = {
        "spec": spec.payload(),
        "spec_hash": content_hash(spec.payload()),
        "files": dict(sorted(files.items())),
    }
    manifest: Manifest = {**body, "manifest_hash": content_hash(body)}  # type: ignore[typeddict-item]
    manifest_path = out_dir / "bars" / "MANIFEST.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    # `--wide` selects the broader cross-section. A flag rather than a second target, so the
    # spec that produced a panel is visible in the command that made it.
    wide = "--wide" in args
    positional = [a for a in args if not a.startswith("-")]
    out_dir = Path(positional[0]) if positional else Path("fixtures")
    manifest = generate(out_dir, WIDE_SPEC if wide else None)
    print(f"fixtures written to {out_dir}: {len(manifest['files'])} files")
    print(f"manifest_hash={manifest['manifest_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
