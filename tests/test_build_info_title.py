"""Tests for packaged-app title fallback to version when git is unavailable.

Verifies that when sha is empty (no git), the window title falls back to the
release version instead of bare "MetaTV". Also ensures all existing git-available
cases remain unchanged (regression guards).
"""

from __future__ import annotations


from metatv.core.build_info import compose_title


class TestVersionFallback:
    """Tests for title fallback when git identity is unavailable (empty sha)."""

    def test_empty_sha_with_version_shows_version(self):
        """When sha is empty, title includes the provided version."""
        title = compose_title("", dirty=False, pr="", branch="", version="9.9.9")
        assert "9.9.9" in title
        assert title != "MetaTV"

    def test_empty_sha_version_formatted_correctly(self):
        """When sha is empty, title format is 'MetaTV <version>'."""
        title = compose_title("", dirty=False, pr="", branch="", version="9.9.9")
        assert title == "MetaTV 9.9.9"

    def test_empty_sha_dirty_flag_ignored(self):
        """Dirty flag is ignored when sha is empty (dirty applies only to git case)."""
        title_clean = compose_title("", dirty=False, pr="", branch="", version="1.0.0")
        title_dirty = compose_title("", dirty=True, pr="", branch="", version="1.0.0")
        # Both should be the same since dirty only affects git commit display
        assert title_clean == "MetaTV 1.0.0"
        assert title_dirty == "MetaTV 1.0.0"

    def test_empty_sha_pr_ignored(self):
        """PR number is ignored when sha is empty."""
        title_no_pr = compose_title("", dirty=False, pr="", branch="", version="1.0.0")
        title_with_pr = compose_title("", dirty=False, pr="123", branch="", version="1.0.0")
        # Both should be the same since PR only affects git commit display
        assert title_no_pr == "MetaTV 1.0.0"
        assert title_with_pr == "MetaTV 1.0.0"

    def test_empty_sha_branch_ignored(self):
        """Branch name is ignored when sha is empty."""
        title_no_branch = compose_title("", dirty=False, pr="", branch="", version="1.0.0")
        title_with_branch = compose_title("", dirty=False, pr="", branch="main", version="1.0.0")
        # Both should be the same since branch only affects git commit display
        assert title_no_branch == "MetaTV 1.0.0"
        assert title_with_branch == "MetaTV 1.0.0"


class TestGitAvailableCasesUnchanged:
    """Regression guards: ensure existing git-available cases still work."""

    def test_pr_checkout_shows_commit_then_pr(self):
        """PR checkout (detached) shows commit hash and PR number."""
        assert compose_title("b3760bd", False, "298", "HEAD") == "MetaTV (b3760bd PR#298)"

    def test_pr_checkout_dirty_appends_star(self):
        """PR checkout with dirty tree appends asterisk to commit hash."""
        assert compose_title("b3760bd", True, "298", "HEAD") == "MetaTV (b3760bd* PR#298)"

    def test_named_branch_no_pr_shows_branch_then_commit(self):
        """Named branch (no PR) shows branch name then commit hash."""
        assert compose_title("b3760bd", False, "", "main") == "MetaTV (main b3760bd)"

    def test_named_branch_dirty(self):
        """Named branch with dirty tree appends asterisk to commit hash."""
        assert compose_title("b3760bd", True, "", "main") == "MetaTV (main b3760bd*)"

    def test_detached_no_pr_shows_commit_only(self):
        """Detached HEAD (no PR) shows commit hash only."""
        assert compose_title("b3760bd", False, "", "HEAD") == "MetaTV (b3760bd)"

    def test_detached_dirty(self):
        """Detached HEAD with dirty tree appends asterisk to commit hash."""
        assert compose_title("b3760bd", True, "", "HEAD") == "MetaTV (b3760bd*)"


def test_no_git_uses_real_package_version_by_default():
    """The SHIPPED path: no git, no injected version — must resolve
    ``metatv.__version__`` itself.

    Every other no-git test passes ``version=`` explicitly, so none of them
    exercise the default-argument resolution the packaged app actually relies
    on.  If the lazy import broke or the default were empty, this is the only
    test that would notice.
    """
    import metatv

    title = compose_title("", False, None, "")
    assert title == f"MetaTV {metatv.__version__}"
    assert title != "MetaTV"
