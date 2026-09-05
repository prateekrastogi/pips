"""`pips universe prerank <root> --as-of YYYY-MM-DD [--n 500] [--config PATH]`: the actual 500.

Reads `<root>/daily/bars_1d.parquet`, assembles `DailyStats` over the configured lookback, runs
`prerank_for_capture`, and writes ONE append-only artifact at
`<root>/universes/prerank-<as_of>.json`.
The same as-of twice is a refusal, not an overwrite: a re-run that would pick a different 500 for
the same day is a fact to be seen, not a file to be replaced.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from pips import cli
from pips.universe import prerank as prerank_module
from pips.universe.daily_stats import daily_stats_from_panel
from pips.universe.prerank import prerank_for_capture

D0 = date(2026, 6, 1)
AS_OF = D0 + timedelta(days=2)


def panel_rows(symbols: list[str], sessions: int = 3) -> pl.DataFrame:
    rows = []
    for k, sym in enumerate(symbols):
        base = 10_000 * (k + 1)
        for i in range(sessions):
            close = base + 100 * i
            rows.append(
                {
                    "trade_date": D0 + timedelta(days=i),
                    "symbol": sym,
                    "isin": f"INE{sym}",
                    "open_paise": close - 50 * (k % 2),
                    "high_paise": close + 100,
                    "low_paise": close - 100,
                    "close_paise": close,
                    "volume": 1_000 * (k + 1) + 10 * i,
                    "received_at_ns": 0,
                }
            )
    return pl.DataFrame(rows)


def archive(tmp_path: Path, symbols: list[str], *, short: Sequence[str] = ()) -> Path:
    frame = panel_rows(symbols)
    if short:
        frame = pl.concat([frame, panel_rows(list(short), sessions=1)])
    (tmp_path / "daily").mkdir()
    frame.write_parquet(tmp_path / "daily" / "bars_1d.parquet")
    cfg = tmp_path / "gap_rate.yaml"
    cfg.write_text(
        "schema_version: 1\nthreshold: 0.03\nlookback_sessions: 3\n"
        "exclude_corporate_actions: true\n"
    )
    return tmp_path


def run(root: Path, *extra: str) -> int:
    return prerank_module.main(
        [str(root), "--as-of", AS_OF.isoformat(), "--config", str(root / "gap_rate.yaml"), *extra]
    )


SIX = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]


def test_it_writes_the_artifact_and_the_selection_is_the_library_selection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, SIX)
    assert run(root, "--n", "4") == 0
    artifact = json.loads((root / "universes" / f"prerank-{AS_OF.isoformat()}.json").read_text())
    stats = daily_stats_from_panel(
        root / "daily" / "bars_1d.parquet", as_of=AS_OF, lookback_sessions=3, gap_threshold=0.03
    ).stats
    expected = prerank_for_capture(stats, n=4, as_of=AS_OF)
    assert artifact["selected"] == list(expected.selected)
    assert artifact["ranked"] == list(expected.ranked)
    assert artifact["as_of"] == AS_OF.isoformat()
    assert artifact["n"] == 4
    assert artifact["lookback_sessions"] == 3 and artifact["gap_threshold"] == 0.03
    out = capsys.readouterr().out
    assert "4 selected" in out and "prerank-" in out


def test_no_daily_panel_is_not_a_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "gap_rate.yaml").write_text("threshold: 0.03\nlookback_sessions: 3\n")
    assert run(tmp_path) == 0
    out = capsys.readouterr().out
    assert "not a pass" in out and "daily promote" in out
    assert not (tmp_path / "universes").exists()


def test_an_existing_artifact_for_the_same_as_of_is_a_refusal_not_an_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, SIX)
    assert run(root, "--n", "4") == 0
    path = root / "universes" / f"prerank-{AS_OF.isoformat()}.json"
    before = path.read_bytes()
    capsys.readouterr()
    assert run(root, "--n", "2") == 1
    assert path.read_bytes() == before
    assert "already exists" in capsys.readouterr().err


def test_as_of_is_required_not_defaulted_to_today(tmp_path: Path) -> None:
    root = archive(tmp_path, SIX)
    with pytest.raises(SystemExit) as stop:
        prerank_module.main([str(root), "--config", str(root / "gap_rate.yaml")])
    assert stop.value.code == 2


def test_reader_exclusions_are_carried_into_the_artifact_with_their_reason(tmp_path: Path) -> None:
    root = archive(tmp_path, SIX, short=["SHORT"])
    assert run(root, "--n", "4") == 0
    artifact = json.loads((root / "universes" / f"prerank-{AS_OF.isoformat()}.json").read_text())
    assert "SHORT" in artifact["excluded"]
    assert "1 of 3" in artifact["excluded"]["SHORT"]
    assert "SHORT" not in artifact["ranked"]


def test_no_pit_store_is_said_aloud_because_ca_gaps_then_count_as_gaps(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, SIX)
    assert run(root, "--n", "4") == 0
    out = capsys.readouterr().out
    assert "no PIT store" in out and "corporate-action" in out


def test_n_is_a_maximum_and_a_short_selection_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, SIX)
    assert run(root, "--n", "50") == 0
    artifact = json.loads((root / "universes" / f"prerank-{AS_OF.isoformat()}.json").read_text())
    assert len(artifact["selected"]) == 6
    # The full phrase: pytest names tmp_path after this test, the CLI prints that path, and the
    # bare word "maximum" was in stdout with the message deleted. A mutant lived on that.
    assert "n is a maximum" in capsys.readouterr().out


def test_the_dispatcher_routes_universe_prerank_and_the_usage_table_documents_it(
    tmp_path: Path,
) -> None:
    root = archive(tmp_path, SIX)
    assert (
        cli.main(
            [
                "universe",
                "prerank",
                str(root),
                "--as-of",
                AS_OF.isoformat(),
                "--config",
                str(root / "gap_rate.yaml"),
                "--n",
                "4",
            ]
        )
        == 0
    )
    assert (root / "universes" / f"prerank-{AS_OF.isoformat()}.json").exists()
    assert any(line.strip().startswith("universe prerank") for line in cli._USAGE.splitlines())


def test_the_default_config_is_the_repo_yaml(tmp_path: Path) -> None:
    root = archive(tmp_path, SIX)
    # The repo's lookback is 60 sessions; a 3-session panel admits nobody under it, which is the
    # honest outcome and proves the default was read rather than a built-in 3.
    assert prerank_module.main([str(root), "--as-of", AS_OF.isoformat(), "--n", "4"]) == 0
    artifact = json.loads((root / "universes" / f"prerank-{AS_OF.isoformat()}.json").read_text())
    assert artifact["lookback_sessions"] == 60
    assert artifact["selected"] == []


def test_a_pit_store_when_present_is_consulted_for_every_overnight_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = archive(tmp_path, SIX)
    (root / "pit").mkdir()
    asked: list[tuple[str, date, int, int]] = []

    def fake_explainer(pit_root: Path) -> object:
        assert pit_root == root / "pit"

        def explain(symbol: str, day: date, prev_close: int, open_paise: int) -> None:
            asked.append((symbol, day, prev_close, open_paise))
            return None

        return explain

    monkeypatch.setattr("pips.data.pit.explain.jump_explainer", fake_explainer)
    assert run(root, "--n", "4") == 0
    # six symbols, three sessions each: two overnight pairs per symbol
    assert len(asked) == 12
    assert {a[0] for a in asked} == set(SIX)


def test_an_unwritable_universes_root_is_refused_before_the_panel_is_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = archive(tmp_path, SIX)
    (root / "universes").write_text("a file where the directory should be")
    assert run(root, "--n", "4") == 2
    err = capsys.readouterr().err
    assert "cannot write" in err and str(root / "universes") in err
