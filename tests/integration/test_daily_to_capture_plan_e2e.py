"""End to end over fixtures, through the real CLI: daily promote -> universe prerank ->
capture PLAN.


Three defects reached arb-vm on 2026-09-05 that no unit test could see: a 26-minute panel build
dying on a directory it could not create, a doubled panel (every range fetched twice), and a
memory profile that scaled with days. This test runs the three commands as subprocesses over a
fixture root shaped like the plant -- two replies per range, a PIT master, a read-only output root
for the refusal path -- so the wiring between them is exercised before a 30-minute VM run is.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import polars as pl
import pytest

from pips.data.pit.instruments import Instrument, InstrumentMaster
from pips.data.pit.store import PitStore

REPO = Path(__file__).resolve().parents[2]
D0 = date(2026, 6, 1)
SESSIONS = [D0 + timedelta(days=i) for i in range(4)]
NAMES = [
    ("RELIANCE", "RELIND", "INE002A01018"),
    ("ICICIBANK", "ICIBAN", "INE090A01021"),
    ("TCS", "TCS", "INE467B01029"),
]


def range_record(vendor: str, *, received: int, bump: float = 0.0) -> dict[str, object]:
    bars = []
    for i, day in enumerate(SESSIONS):
        close = 100.0 + 10 * i + bump
        bars.append(
            {
                "datetime": f"{day.isoformat()} 00:00:00",
                "open": close - 1,
                "high": close + 2,
                "low": close - 2,
                "close": close,
                "volume": 1000 * (i + 1),
                "stock_code": vendor,
                "exchange_code": "NSE",
            }
        )
    return {
        "request": {
            "symbol": vendor,
            "interval": "1day",
            "from": f"{SESSIONS[0]}T00:00:00.000Z",
            "to": f"{SESSIONS[-1]}T15:30:00.000Z",
        },
        "received_at_ns": received,
        "payload": {"Status": 200, "Error": None, "Success": bars},
    }


def plant(tmp_path: Path) -> Path:
    root = tmp_path / "srv"
    master = InstrumentMaster(PitStore(root / "pit"))
    for k, (symbol, vendor, isin) in enumerate(NAMES):
        master.upsert(
            Instrument(
                isin=isin,
                exchange_token=str(2000 + k),
                symbol=symbol,
                name=symbol,
                series="EQ",
                lot_size=1,
                tick_size_paise=5,
                vendor_code=vendor,
            ),
            known_from=date(2020, 1, 1),
        )
        d = root / "bronze" / vendor / "1day" / f"{SESSIONS[0]}_{SESSIONS[-1]}"
        d.mkdir(parents=True)
        # every range answered twice, the second a correction -- the plant's shape today
        (d / "a.json").write_text(
            json.dumps(range_record(vendor, received=1_000)), encoding="utf-8"
        )
        (d / "b.json").write_text(
            json.dumps(range_record(vendor, received=2_000, bump=1.0)), encoding="utf-8"
        )
    (root / "gap_rate.yaml").write_text("threshold: 0.03\nlookback_sessions: 3\n", encoding="utf-8")
    return root


def pips(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(REPO / "python")}
    return subprocess.run(
        [sys.executable, "-m", "pips.cli", *args],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_promote_prerank_and_capture_plan_chain_over_a_plant_shaped_root(tmp_path: Path) -> None:
    root = plant(tmp_path)

    promote = pips("daily", "promote", str(root), "--known-on", SESSIONS[-1].isoformat())
    assert promote.returncode == 0, promote.stdout + promote.stderr
    assert "12 superseded" in promote.stdout  # the first replies, counted aloud
    panel = pl.read_parquet(root / "daily" / "bars_1d.parquet")
    assert panel.height == 12
    assert panel.group_by(["isin", "trade_date"]).len()["len"].max() == 1
    assert panel["close_paise"].min() == 10100  # the corrected (later) closes won

    prerank = pips(
        "universe",
        "prerank",
        str(root),
        "--as-of",
        SESSIONS[-1].isoformat(),
        "--config",
        str(root / "gap_rate.yaml"),
        "--n",
        "2",
    )
    assert prerank.returncode == 0, prerank.stdout + prerank.stderr
    artifact = root / "universes" / f"prerank-{SESSIONS[-1].isoformat()}.json"
    selected = json.loads(artifact.read_text())["selected"]
    assert len(selected) == 2 and set(selected) <= {s for s, _, _ in NAMES}

    plan = pips(
        "capture", str(root), "--shortlist", str(artifact), "--now", "2026-09-06T10:00:00+05:30"
    )
    assert plan.returncode == 0, plan.stdout + plan.stderr
    codes = {v for s, v, _ in NAMES if s in selected}
    assert "capture: 2 symbol(s): " in plan.stdout
    assert all(code in plan.stdout for code in codes)
    assert "--live" not in plan.stdout or "PLAN" in plan.stdout  # a plan, nothing opened
    assert not (root / "ws").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_an_unwritable_output_root_refuses_in_seconds_not_after_the_build(tmp_path: Path) -> None:
    root = plant(tmp_path)
    (root / "daily").mkdir()
    (root / "daily").chmod(0o500)
    try:
        promote = pips("daily", "promote", str(root), "--known-on", SESSIONS[-1].isoformat())
    finally:
        (root / "daily").chmod(0o700)
    assert promote.returncode == 2
    assert "cannot write" in promote.stderr
    assert "range record" not in promote.stdout
