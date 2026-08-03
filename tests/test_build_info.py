"""Behavioral tests for the window-title build-info composition.

The git-touching parts (`window_title`, `_git`) are exercised only through their
pure core: `compose_title` (the string builder) and `_pr_number` (the dir-name
parser, with `repo_dir` monkeypatched). No live git calls — deterministic.
"""

from __future__ import annotations

from pathlib import Path

from metatv.core import build_info
from metatv.core.build_info import compose_title


class TestComposeTitle:
    def test_pr_checkout_shows_commit_then_pr(self):
        # run.sh <PR#> runs detached, so branch == "HEAD" and is ignored in favour of PR#.
        assert compose_title("b3760bd", False, "298", "HEAD") == "MetaTV (b3760bd PR#298)"

    def test_pr_checkout_dirty_appends_star(self):
        assert compose_title("b3760bd", True, "298", "HEAD") == "MetaTV (b3760bd* PR#298)"

    def test_named_branch_no_pr_shows_branch_then_commit(self):
        assert compose_title("b3760bd", False, "", "main") == "MetaTV (main b3760bd)"

    def test_named_branch_dirty(self):
        assert compose_title("b3760bd", True, "", "main") == "MetaTV (main b3760bd*)"

    def test_detached_no_pr_shows_commit_only(self):
        assert compose_title("b3760bd", False, "", "HEAD") == "MetaTV (b3760bd)"

    def test_no_git_falls_back_to_version(self):
        # Empty sha (git unavailable / not a repo) → fall back to version string.
        assert compose_title("", False, "298", "main", version="0.24.0") == "MetaTV 0.24.0"


class TestPrNumber:
    def test_parses_pr_from_worktree_dirname(self, monkeypatch):
        monkeypatch.setattr(build_info, "repo_dir", lambda: Path("/home/x/Projects/metatv-pr-298"))
        assert build_info._pr_number() == "298"

    def test_main_checkout_has_no_pr(self, monkeypatch):
        monkeypatch.setattr(build_info, "repo_dir", lambda: Path("/home/x/Projects/metatv"))
        assert build_info._pr_number() == ""

    def test_only_trailing_pr_suffix_matches(self, monkeypatch):
        # A "-pr-" that isn't the trailing dir segment must not be mistaken for a PR.
        monkeypatch.setattr(build_info, "repo_dir", lambda: Path("/home/x/metatv-pr-1-notes"))
        assert build_info._pr_number() == ""


# ---------------------------------------------------------------------------
# Rolling-release build id (v0.26.0) — the packaged app must say which commit
# it is, because the version string alone no longer distinguishes two builds.
# ---------------------------------------------------------------------------

def test_build_id_is_empty_without_a_stamp():
    """A dev checkout has no generated _build_id module."""
    from metatv.core.build_info import build_id

    # metatv/_build_id.py is gitignored and only written by CI, so in the repo
    # this must be absent rather than stale.
    assert build_id() == ""


def test_build_id_reads_the_generated_stamp(monkeypatch, tmp_path):
    """A stamped build reports the id CI wrote."""
    import sys
    import types

    from metatv.core import build_info

    module = types.ModuleType("metatv._build_id")
    module.BUILD_ID = "0.25.0+20260803.a3e7a28"
    monkeypatch.setitem(sys.modules, "metatv._build_id", module)

    assert build_info.build_id() == "0.25.0+20260803.a3e7a28"


def test_packaged_title_prefers_the_build_id_over_the_bare_version(monkeypatch):
    """Without git (the packaged case), the title must identify the COMMIT.

    Pre-rolling this returned "MetaTV 0.25.0", which was fine when 0.25.0 named
    exactly one build. Under rolling releases many builds share a version, so a
    bug report quoting the title has to be resolvable to a commit.
    """
    import sys
    import types

    from metatv.core import build_info

    module = types.ModuleType("metatv._build_id")
    module.BUILD_ID = "0.25.0+20260803.a3e7a28"
    monkeypatch.setitem(sys.modules, "metatv._build_id", module)

    title = build_info.compose_title("", False, "", "")

    assert title == "MetaTV 0.25.0+20260803.a3e7a28", (
        f"packaged title must carry the build id, got {title!r}"
    )


def test_packaged_title_falls_back_to_version_when_unstamped():
    """A local PyInstaller run with no CI stamp still gets a sane title."""
    import metatv
    from metatv.core import build_info

    title = build_info.compose_title("", False, "", "")

    assert title == f"MetaTV {metatv.__version__}"


def test_git_checkout_still_wins_over_the_stamp(monkeypatch):
    """A dev checkout has better information than any stamp — the live sha."""
    import sys
    import types

    from metatv.core import build_info

    module = types.ModuleType("metatv._build_id")
    module.BUILD_ID = "0.25.0+20260803.a3e7a28"
    monkeypatch.setitem(sys.modules, "metatv._build_id", module)

    title = build_info.compose_title("deadbee", False, "", "main")

    assert title == "MetaTV (main deadbee)", (
        f"a real checkout must report its own sha, not the stamp; got {title!r}"
    )
