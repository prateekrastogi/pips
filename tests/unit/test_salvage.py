"""The harvest map is machine-checked (§1.2, constitution rule 13).

`ledger/salvage.yaml` gates every connector, adapter and downloader we will ever write, so
a row that lies — a commit that does not contain its path, a NONE_FOUND that never searched
— is worse than no row at all. These checks are what make "I looked" auditable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pips.ledger.salvage import (
    Decision,
    SalvageRow,
    check_salvage,
    load_salvage,
    main,
)

ROOT = Path(__file__).resolve().parents[2]


def _donor(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "SAL-0001",
        "component": "Breeze session-token bootstrap",
        "repo": "intraday",
        "path": "src/volarb/adapters/breeze/auth.py",
        "commit": "be8186d4262a",
        "ref": "main",
        "found_at_head": False,
        "size_bytes": 1451,
        "decision": "PORT",
        "covers_needs": ["M4 session-token flow"],
        "notes": "daily session bootstrap",
    }
    row.update(over)
    return row


def _none_found(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "SAL-0022",
        "component": "Flattrade order client",
        "decision": "NONE_FOUND",
        "covers_needs": ["M23 broker-flattrade adapter"],
        "searched": {
            "repos": ["convexity", "intraday", "vol_research"],
            "refs": ["main", "origin/hardening"],
            "tags": [],
            "keywords": ["flattrade", "noren"],
            "method": "paths across all refs + git grep over every reachable commit",
        },
        "notes": "from-scratch is pre-authorized",
    }
    row.update(over)
    return row


def test_a_donor_row_validates() -> None:
    assert SalvageRow.model_validate(_donor()).decision is Decision.PORT


def test_a_donor_row_must_carry_a_source_commit() -> None:
    # §1.2: "every salvage row carries a source commit SHA". Donors are frequently NOT at
    # HEAD, so a row without a SHA cannot be resolved back to the code it claims.
    with pytest.raises(ValueError, match="commit"):
        SalvageRow.model_validate(_donor(commit=None))


@pytest.mark.parametrize(
    "bad", ["HEAD", "be8186", "zzzzzzzzzzzz", "be8186d4262a1234567890123456789012345678901"]
)
def test_a_commit_must_look_like_a_sha(bad: str) -> None:
    with pytest.raises(ValueError):
        SalvageRow.model_validate(_donor(commit=bad))


def test_a_donor_row_must_name_a_path() -> None:
    with pytest.raises(ValueError, match="path"):
        SalvageRow.model_validate(_donor(path=None))


def test_a_none_found_row_validates_without_a_commit() -> None:
    assert SalvageRow.model_validate(_none_found()).decision is Decision.NONE_FOUND


def test_a_none_found_row_must_record_what_was_searched() -> None:
    # "I didn't look" is not valid provenance (§1.1 rule 4).
    with pytest.raises(ValueError, match="searched"):
        SalvageRow.model_validate(_none_found(searched=None))


def test_a_none_found_row_must_name_refs_and_keywords() -> None:
    base: dict[str, Any] = _none_found()
    for missing in ("refs", "keywords"):
        payload: dict[str, Any] = dict(base["searched"])
        payload[missing] = []
        with pytest.raises(ValueError, match=missing):
            SalvageRow.model_validate(_none_found(searched=payload))


def test_every_row_must_cover_at_least_one_need() -> None:
    with pytest.raises(ValueError, match="covers_needs"):
        SalvageRow.model_validate(_donor(covers_needs=[]))


def test_repo_salvage_file_is_valid_and_ids_unique() -> None:
    rows = load_salvage(ROOT / "docs" / "ledger" / "salvage.yaml")
    ids = [r.id for r in rows]
    assert len(ids) == len(set(ids)), "duplicate SAL ids"
    assert rows, "M1 has run: salvage.yaml must not be empty"


def test_every_infrastructure_need_is_covered_or_declared_none_found() -> None:
    # The needs-coverage table §1.2 demands: every M4/M6/M21-M23 need names a donor or has
    # a NONE_FOUND row. This is the check that stops a connector being written blind.
    failures = check_salvage(ROOT)
    assert failures == [], "\n".join(failures)


def test_donor_rows_are_verified_against_real_blobs(tmp_path: Path) -> None:
    # A row claims `git show <commit>:<path>` resolves. That claim is checkable, and a
    # harvest map whose SHAs do not resolve is worse than none — it reads as provenance
    # while pointing at nothing. (An earlier draft of this very file had four such rows.)
    import subprocess

    from pips.ledger.salvage import verify_donors

    past = tmp_path / "past"
    repo = past / "donor"
    repo.mkdir(parents=True)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (repo / "real.py").write_text("x = 1\n")
    git("add", "-A")
    git("commit", "-qm", "add")
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()[:12]

    good = SalvageRow.model_validate(_donor(repo="donor", path="real.py", commit=sha, size_bytes=6))
    assert verify_donors([good], past) == []

    # A row whose recorded size no longer matches the blob is a stale row, and stale
    # provenance is the failure mode this whole file exists to prevent.
    stale = SalvageRow.model_validate(
        _donor(repo="donor", path="real.py", commit=sha, size_bytes=9999)
    )
    assert len(verify_donors([stale], past)) == 1

    missing = SalvageRow.model_validate(
        _donor(repo="donor", path="ghost.py", commit=sha, size_bytes=6)
    )
    failures = verify_donors([missing], past)
    assert len(failures) == 1 and "ghost.py" in failures[0]


def test_an_absent_past_directory_is_reported_as_absent_not_as_21_broken_donors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`../past` was deleted on 2026-09-04, deliberately, after the harvest completed.

    Before this, running the verifier without it printed one failure PER ROW —
    "SAL-0019: no git repo at ../past/convexity", twenty-one times — which reads exactly like a
    corrupted or half-cloned harvest source. A folder that was removed on purpose and a folder
    whose donors have gone missing are different states, and they were being reported
    identically.

    The register's header carries the `git clone` lines that restore it; this points there
    rather than making the reader work out that nothing is actually wrong.
    """
    missing = tmp_path / "not-here"
    code = main([str(missing)])

    out = capsys.readouterr().out
    assert code == 1, "still a failure: the check genuinely did not run"
    assert "does not exist" in out, out
    assert "git clone" in out, "the reader needs the way back, not just the bad news"
    assert out.count("no git repo") == 0, "a missing root is one fact, not one per donor row"
