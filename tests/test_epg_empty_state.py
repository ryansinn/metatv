"""Tests for the honest EPG empty state (task #17).

Owner report: the EPG view said "No EPG sources" for four situations that call
for four different responses — no sources at all, sources with no guide URL, EPG
deliberately switched off, and a fully-configured setup that simply hasn't
fetched yet. Only the last is a "press Refresh" case; two of the others are not
problems at all, and the flat wording sent the user hunting for a fault that
didn't exist.

Covers the pure classifier (every branch, because each one is a distinct user
action) and the repository counts that feed it, against a real file-backed
Database per the project convention.

The EPG chip stays enabled in every case — owner call. These messages explain,
they never gate navigation.
"""

from __future__ import annotations

import pytest

from metatv.gui.epg_view import epg_empty_state


def _readiness(total=0, with_url=0, enabled=0, eligible=0) -> dict:
    return {"total": total, "with_url": with_url, "enabled": enabled,
            "eligible": eligible}


class TestClassifier:

    def test_data_present_says_nothing(self):
        """A working guide needs no explanation — both strings empty."""
        headline, hint = epg_empty_state(
            _readiness(total=1, with_url=1, enabled=1, eligible=1), 5000
        )
        assert (headline, hint) == ("", "")

    def test_no_sources_at_all(self):
        headline, hint = epg_empty_state(_readiness(total=0), 0)
        assert "No sources yet" == headline
        assert "Add a source" in hint

    def test_epg_switched_off_is_not_reported_as_missing(self):
        """The user turned it off deliberately; say so, don't imply breakage."""
        headline, hint = epg_empty_state(
            _readiness(total=2, with_url=2, enabled=0, eligible=0), 0
        )
        assert headline == "TV guide is turned off"
        assert "Sources" in hint and "EPG" in hint
        assert "Refresh" not in hint, (
            "must not tell the user to Refresh — refreshing cannot help while "
            "EPG is switched off"
        )

    def test_sources_publish_no_guide_url(self):
        headline, hint = epg_empty_state(
            _readiness(total=2, with_url=0, enabled=2, eligible=0), 0
        )
        assert headline == "No guide available from your sources"
        assert "XMLTV" in hint, "should point at the manual-URL escape hatch"

    def test_partially_configured(self):
        """Some sources have a URL, some have it enabled, but none have both."""
        headline, hint = epg_empty_state(
            _readiness(total=2, with_url=1, enabled=1, eligible=0), 0
        )
        assert headline == "TV guide is not set up"
        assert "guide URL" in hint and "switch" in hint

    def test_ready_but_never_fetched_is_the_only_refresh_case(self):
        headline, hint = epg_empty_state(
            _readiness(total=1, with_url=1, enabled=1, eligible=1), 0
        )
        assert headline == "Guide not downloaded yet"
        assert "Refresh Guide" in hint

    def test_every_branch_is_actionable(self):
        """No branch may return a bare headline with no next step."""
        cases = [
            _readiness(total=0),
            _readiness(total=2, with_url=2, enabled=0, eligible=0),
            _readiness(total=2, with_url=0, enabled=2, eligible=0),
            _readiness(total=2, with_url=1, enabled=1, eligible=0),
            _readiness(total=1, with_url=1, enabled=1, eligible=1),
        ]
        for readiness in cases:
            headline, hint = epg_empty_state(readiness, 0)
            assert headline and hint, f"{readiness} produced {headline!r}/{hint!r}"

    def test_tolerates_a_missing_readiness_dict(self):
        """The view passes ``{}`` before the first load — must not raise."""
        headline, hint = epg_empty_state({}, 0)
        assert headline == "No sources yet"


class TestReadinessCounts:
    """The repository half, against a real Database on a tmp_path file."""

    @pytest.fixture()
    def repos(self, tmp_path):
        from metatv.core.database import Database
        from metatv.core.repositories import RepositoryFactory

        db = Database(f"sqlite:///{tmp_path}/epg_readiness.db")
        db.create_tables()
        session = db.get_session()
        yield RepositoryFactory(session), session
        session.close()

    def _add(self, session, pid, *, epg_url, epg_enabled, is_active=True):
        from metatv.core.database import ProviderDB

        # effective_epg_url derives from credentials + urls, never the cached
        # epg_url column — so ``urls`` (the actual derivation input) must track
        # epg_url's truthiness ("has a URL" vs "no URL derivable") for these
        # with_url/eligible counts to mean what the test names say.
        urls = '[{"url": "http://x", "primary": true}]' if epg_url else '[]'
        session.add(ProviderDB(
            id=pid, name=pid, type="xtream", url="http://x",
            urls=urls,
            username="u", password="p", is_active=is_active,
            epg_url=epg_url, epg_enabled=epg_enabled,
        ))
        session.commit()

    def test_counts_separate_url_from_enabled(self, repos):
        factory, session = repos
        self._add(session, "has-both", epg_url="http://g", epg_enabled=True)
        self._add(session, "no-url", epg_url=None, epg_enabled=True)
        self._add(session, "disabled", epg_url="http://g", epg_enabled=False)

        counts = factory.providers.get_epg_readiness()

        assert counts["total"] == 3
        assert counts["with_url"] == 2, "url presence is independent of the switch"
        assert counts["enabled"] == 2, "the switch is independent of url presence"
        assert counts["eligible"] == 1, "only the source with BOTH is eligible"

    def test_total_counts_inactive_sources_too(self, repos):
        """"You have no sources" must stay distinguishable from "your sources
        are all switched off" — so total is not filtered by is_active."""
        factory, session = repos
        self._add(session, "off", epg_url="http://g", epg_enabled=True,
                  is_active=False)

        counts = factory.providers.get_epg_readiness()

        assert counts["total"] == 1
        assert counts["eligible"] == 0

    def test_empty_install(self, repos):
        factory, _session = repos
        counts = factory.providers.get_epg_readiness()
        assert counts == {"total": 0, "with_url": 0, "enabled": 0, "eligible": 0}

    def test_classifier_consumes_repository_output_directly(self, repos):
        """End-to-end shape check: whatever the repo returns must satisfy the
        classifier without translation, or the two will drift."""
        factory, session = repos
        self._add(session, "disabled", epg_url="http://g", epg_enabled=False)

        headline, hint = epg_empty_state(factory.providers.get_epg_readiness(), 0)

        assert headline == "TV guide is turned off"
        assert hint
