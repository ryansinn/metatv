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

    def test_no_git_falls_back_to_plain(self):
        # Empty sha (git unavailable / not a repo) → no suffix at all.
        assert compose_title("", False, "298", "main") == "MetaTV"


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
