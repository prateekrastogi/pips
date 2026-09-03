"""Every Rust crate is in the workspace  (gate integrity, rule 10).

`make ci` runs `cargo test --workspace`, which tests the crates the workspace *lists*. A crate
that exists on disk and is missing from `members` is not tested, not linted by
`cargo clippy --workspace`, and reports nothing at all — the build stays green because the crate
is invisible to it, which is the same shape as a pytest file the suite never collects.

Nothing today: 21 crates on disk, 21 listed. This is the guard, not the fix — the hole opens the
day someone adds the twenty-second and the diff looks complete without the manifest line.

**The crates are scaffolds and their emptiness is honest.** 147 lines of Rust across all 21, each
saying *"Scaffold only (M0). Implementation lands under M21 test-first."*, and all six contract
rows pointing at them are `planned`, the weakest status. So `cargo test` passing with zero test
functions is a true report about a plant that has not been built yet, not a vacuous green — and
this test deliberately does not require tests to exist, because requiring them now would force
either a fake test or a suppression, and both are worse than an honest zero.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_every_crate_on_disk_is_a_workspace_member() -> None:
    """Otherwise it is neither tested nor linted, and nothing says so."""
    manifest = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))
    members = {m for m in manifest["workspace"]["members"] if m.startswith("rust/crates/")}
    on_disk = {
        f"rust/crates/{path.name}"
        for path in (ROOT / "rust" / "crates").iterdir()
        if (path / "Cargo.toml").exists()
    }

    assert on_disk - members == set(), (
        f"crates on disk but absent from the workspace, so `cargo test --workspace` never sees "
        f"them: {sorted(on_disk - members)}"
    )
    assert members - on_disk == set(), (
        f"crates listed in the workspace with no manifest on disk: {sorted(members - on_disk)}"
    )


def test_the_ladder_tests_the_whole_workspace_not_a_named_list() -> None:
    """`--workspace`, so adding a member is enough to have it covered.

    A hand-listed set of crates in the Makefile would need updating in two places, and the one
    that is forgotten is always the one that runs the tests.
    """
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("rust-test:")[1].split("\n\n")[0]

    assert re.search(r"cargo test\s+--workspace", recipe), recipe
    assert re.search(r"cargo clippy\s+--workspace", recipe), recipe
