"""Behavioral tests for the redesigned Similar-Titles lightbox.

Three concerns, each asserting the outcome that would break:

1. **Ratings + suppression display (real-bug fix).** ``SimilarTitleLightbox._bg_load``
   used to read ``getattr(ch, "user_rating", 0)`` / ``getattr(ch, "is_suppressed",
   False)`` off ``ChannelDB`` — columns that do not exist — so the Like / Dislike /
   Not-Interested buttons never lit up. The rebuilt loader must read real like/dislike
   from ``UserRatingDB`` and real suppression from ``ChannelDB.is_rec_suppressed``.
   (These tests FAIL against the old getattr-off-ChannelDB code.)

2. **Other Versions = provider-scoped content_key siblings.** The badge count and the
   Other Versions row read the stored ``content_key`` via
   ``ChannelRepository.get_content_key_siblings`` with the SAME absolute gate as
   Similar Titles (#326 / DR-0007): disabled/expired sources never surface.

3. **Discoverability affordance.** Each details-pane Similar row exposes a ⤢ control
   whose LEFT-click emits ``similar_preview_requested`` with the right (ids, index,
   origin); the name button's right-click path is still present.

All DB tests use a file-backed tmp_path SQLite (not :memory:).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_db(path: Path):
    from metatv.core.database import Database
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    return db


def _fake_config():
    """Minimal duck-typed Config for ``preference_engine.version_score``."""
    return SimpleNamespace(
        preferred_version_prefixes=[],
        preferred_version_provider_ids=[],
        preferred_version_quality=None,
    )


def _fake_metadata_manager(result=None):
    """A stand-in MetadataManager whose async ``get_metadata`` returns *result*.

    The lightbox now enriches the main card through this seam; these display/scoping
    tests don't exercise the fetched fields, so the default returns ``None`` (the
    "no rich metadata" path). ``.calls`` records each channel id fetched.
    """
    class _FakeMM:
        def __init__(self):
            self.calls: list[str] = []

        async def get_metadata(self, channel_id, force_refresh=False):
            self.calls.append(channel_id)
            return result

    return _FakeMM()


def _make_provider(session, pid: str, *, is_active: bool = True, exp=None):
    from metatv.core.database import ProviderDB
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=is_active, account_exp_date=exp,
    ))
    session.flush()


def _make_channel(session, *, cid, name, provider_id, content_key,
                  media_type="movie", is_hidden=False, is_rec_suppressed=False,
                  detected_quality=None, detected_region=None):
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        content_key=content_key,
        is_hidden=is_hidden,
        is_rec_suppressed=is_rec_suppressed,
        detected_quality=detected_quality,
        detected_region=detected_region,
    )
    session.add(ch)
    session.flush()
    return ch


def _set_rating(session, channel_id: str, rating: int):
    from metatv.core.database import UserRatingDB
    session.merge(UserRatingDB(channel_id=channel_id, rating=rating, rated_at=datetime.utcnow()))
    session.flush()


def _lightbox_for(db):
    """A SimilarTitleLightbox with just the attrs ``_bg_load`` touches (no Qt tree)."""
    from metatv.gui.similar_lightbox import SimilarTitleLightbox

    calls: list[tuple] = []

    class _FakeSignal:
        def emit(self, cid, data):
            calls.append((cid, data))

    lb = SimilarTitleLightbox.__new__(SimilarTitleLightbox)
    lb._db = db
    lb._config = _fake_config()
    lb._metadata_manager = _fake_metadata_manager()
    lb._data_ready = _FakeSignal()
    lb._calls = calls
    return lb


def _load(db, channel_id: str) -> dict:
    lb = _lightbox_for(db)
    lb._bg_load(channel_id)
    assert lb._calls, "lightbox emitted no data"
    return lb._calls[0][1]


# ---------------------------------------------------------------------------
# 1. Ratings + suppression display (the real-bug fix)
# ---------------------------------------------------------------------------

class TestRatingSuppressionDisplay:
    def test_like_reflected(self, tmp_path):
        db = _make_db(tmp_path / "rate_like.db")
        with db.session_scope() as session:
            _make_provider(session, "p1")
            _make_channel(session, cid="ch-like", name="Some Movie",
                          provider_id="p1", content_key="k-like|movie")
            _set_rating(session, "ch-like", 1)

        data = _load(db, "ch-like")
        assert data.get("user_rating") == 1, "a +1 UserRatingDB row must drive Like checked"
        assert data.get("is_suppressed") is False
        db.close()

    def test_dislike_reflected(self, tmp_path):
        db = _make_db(tmp_path / "rate_dislike.db")
        with db.session_scope() as session:
            _make_provider(session, "p1")
            _make_channel(session, cid="ch-dis", name="Some Movie",
                          provider_id="p1", content_key="k-dis|movie")
            _set_rating(session, "ch-dis", -1)

        data = _load(db, "ch-dis")
        assert data.get("user_rating") == -1, "a -1 UserRatingDB row must drive Dislike checked"
        assert data.get("is_suppressed") is False
        db.close()

    def test_suppression_reflected(self, tmp_path):
        db = _make_db(tmp_path / "rate_supp.db")
        with db.session_scope() as session:
            _make_provider(session, "p1")
            _make_channel(session, cid="ch-supp", name="Some Movie", provider_id="p1",
                          content_key="k-supp|movie", is_rec_suppressed=True)

        data = _load(db, "ch-supp")
        assert data.get("is_suppressed") is True, (
            "is_rec_suppressed must drive Not-Interested checked"
        )
        assert (data.get("user_rating") or 0) == 0
        db.close()

    def test_neutral_row_has_no_rating(self, tmp_path):
        db = _make_db(tmp_path / "rate_neutral.db")
        with db.session_scope() as session:
            _make_provider(session, "p1")
            _make_channel(session, cid="ch-neutral", name="Some Movie",
                          provider_id="p1", content_key="k-neutral|movie")

        data = _load(db, "ch-neutral")
        assert (data.get("user_rating") or 0) == 0, "an unrated row shows no like/dislike"
        assert data.get("is_suppressed") is False
        db.close()


# ---------------------------------------------------------------------------
# 2. Other Versions — provider-scoped content_key siblings + ×N count
# ---------------------------------------------------------------------------

class TestOtherVersionsScoping:
    def _seed(self, session):
        now = datetime.now()
        _make_provider(session, "p-active", is_active=True, exp=now + timedelta(days=30))
        _make_provider(session, "p-active2", is_active=True, exp=now + timedelta(days=30))
        _make_provider(session, "p-disabled", is_active=False, exp=now + timedelta(days=30))
        _make_provider(session, "p-expired", is_active=True, exp=now - timedelta(days=1))

        # "12 Monkeys" collapses under one content_key across sources.
        ck = "tmdb:63|movie"
        _make_channel(session, cid="ch-origin", name="12 Monkeys",
                      provider_id="p-active", content_key=ck)
        _make_channel(session, cid="sib-active", name="12 Monos (LATINO)",
                      provider_id="p-active2", content_key=ck, detected_region="LAT")
        _make_channel(session, cid="sib-disabled", name="12 Monkeys 4K",
                      provider_id="p-disabled", content_key=ck, detected_quality="4K")
        _make_channel(session, cid="sib-expired", name="Mision: Salvar el bosque",
                      provider_id="p-expired", content_key=ck, detected_region="ES")

    def test_bg_load_other_versions_excludes_hidden(self, tmp_path):
        db = _make_db(tmp_path / "ov_bgload.db")
        with db.session_scope() as session:
            self._seed(session)

        data = _load(db, "ch-origin")
        ver_ids = {v["id"] for v in (data.get("versions") or [])}

        assert "sib-active" in ver_ids, "an active-source sibling must appear in Other Versions"
        assert "sib-disabled" not in ver_ids, "disabled-source version must never surface"
        assert "sib-expired" not in ver_ids, "expired-source version must never surface"
        assert "ch-origin" not in ver_ids, "the origin itself is excluded"
        assert data.get("version_count") == 1, "×N badge counts only the scoped siblings"
        db.close()

    def test_repo_siblings_scoping_gate(self, tmp_path):
        """The chokepoint gates hidden providers only when passed the exclusion set."""
        from metatv.core.repositories import RepositoryFactory

        db = _make_db(tmp_path / "ov_repo.db")
        with db.session_scope() as session:
            self._seed(session)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            excluded = set(repos.providers.get_hidden_provider_ids())
            assert {"p-disabled", "p-expired"} <= excluded

            scoped = repos.channels.get_content_key_siblings(
                "tmdb:63|movie", "ch-origin", excluded_provider_ids=excluded,
            )
            scoped_ids = {r["id"] for r in scoped}
            # Failover default (no gate) still returns every sibling.
            unscoped_ids = {
                r["id"] for r in repos.channels.get_content_key_siblings(
                    "tmdb:63|movie", "ch-origin",
                )
            }

        assert scoped_ids == {"sib-active"}, f"scoped siblings should be active-only; got {scoped_ids}"
        assert {"sib-active", "sib-disabled", "sib-expired"} <= unscoped_ids, (
            "the ungated failover call must still see every sibling"
        )
        db.close()

    def test_siblings_carry_source_and_tag(self, tmp_path):
        """Other Versions dicts carry a source-tagged label (provider_name + tag)."""
        db = _make_db(tmp_path / "ov_tag.db")
        with db.session_scope() as session:
            self._seed(session)

        data = _load(db, "ch-origin")
        versions = data.get("versions") or []
        assert versions, "expected one scoped version"
        v = versions[0]
        assert v["id"] == "sib-active"
        assert v.get("provider_name") == "p-active2", "each version is tagged by its source"
        assert v.get("tag") == "LAT", "the version tag comes from detected region/quality"
        db.close()


# ---------------------------------------------------------------------------
# 3. Discoverability — ⤢ preview affordance on each details Similar row
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _version(**kw):
    from metatv.gui.details_versions import ChannelVersion
    base = dict(channel_id="c1", name="Show", in_queue=False)
    base.update(kw)
    return ChannelVersion(**base)


def _preview_button(row_w):
    from PyQt6.QtWidgets import QPushButton
    for b in row_w.findChildren(QPushButton):
        if b.toolTip() == "Preview in lightbox":
            return b
    return None


class TestOverlayEndToEnd:
    """Build the REAL overlay (not __new__) and drive show_preview → the card's
    rating button reflects the stored state and Other Versions is scoped."""

    def test_overlay_reflects_state_and_scopes_versions(self, qapp, tmp_path):
        import time

        from PyQt6.QtWidgets import QWidget
        from metatv.core.database import ChannelDB, MetadataDB
        from metatv.core.image_cache import ImageCache
        from metatv.gui.similar_lightbox import SimilarTitleLightbox

        db = _make_db(tmp_path / "overlay_e2e.db")
        now = datetime.now()
        with db.session_scope() as session:
            _make_provider(session, "pa", is_active=True, exp=now + timedelta(days=9))
            _make_provider(session, "pb", is_active=True, exp=now + timedelta(days=9))
            _make_provider(session, "pdis", is_active=False, exp=now + timedelta(days=9))
            session.add(MetadataDB(id="m1", title="12 Monkeys", year=1995, runtime=129,
                                   rating=8.0, genres=["Sci-Fi", "Thriller"],
                                   cast=[{"name": "Bruce Willis"}], director="Terry Gilliam",
                                   plot="A convict is sent back in time."))
            session.flush()
            o = _make_channel(session, cid="ch-o", name="12 Monkeys Origin",
                              provider_id="pa", content_key="tmdb:63|movie")
            o.metadata_id = "m1"
            _make_channel(session, cid="ch-sib", name="12 Monos LATINO",
                          provider_id="pb", content_key="tmdb:63|movie", detected_region="LAT")
            _make_channel(session, cid="ch-sib-dis", name="12 Monkeys 4K",
                          provider_id="pdis", content_key="tmdb:63|movie", detected_quality="4K")
            _set_rating(session, "ch-o", 1)

        parent = QWidget()
        parent.resize(1400, 900)
        parent.show()   # _apply_data guards on isVisible() — the overlay needs a shown ancestor
        ic = ImageCache(cache_dir=str(tmp_path / "imgcache"))
        lb = SimilarTitleLightbox(
            parent, _fake_config(), ic, db, _fake_metadata_manager()
        )
        try:
            lb.show_preview(["ch-o"], 0, "12 Monos LATINO")
            lb._executor.shutdown(wait=True)   # let _bg_load finish
            for _ in range(20):
                qapp.processEvents()            # deliver the queued _data_ready signal
                time.sleep(0.01)

            card = lb._card
            assert lb._current_id == "ch-o"
            assert card._heading_lbl.text() == "12 Monkeys Origin"
            assert card._like_btn.isChecked() is True, "Like must light up from UserRatingDB"
            assert card._not_interested_btn.isChecked() is False
            assert card._versions_hdr.text() == "OTHER VERSIONS (1)", (
                "only the active-source sibling is counted (disabled one gated out)"
            )
        finally:
            lb.deleteLater()
            parent.deleteLater()
            qapp.processEvents()
            db.close()


class TestDiscoverabilityAffordance:
    def test_left_click_emits_preview_request(self, qapp):
        from metatv.core.config import Config
        from metatv.gui.details_similar import _SimilarSection
        from metatv.gui.details_versions import ChannelVersion
        from metatv.gui import icons as _icons

        section = _SimilarSection(Config())
        titles = [
            _version(channel_id="a", name="Alpha"),
            _version(channel_id="b", name="Bravo"),
        ]
        section.load(titles, origin_title="Origin Title")

        emitted: list[tuple] = []
        section.similar_preview_requested.connect(
            lambda ids, idx, origin: emitted.append((ids, idx, origin))
        )

        # The second row's ⤢ button must open the lightbox at index 1.
        row = section._body_layout.itemAt(1).widget()
        btn = _preview_button(row)
        assert btn is not None, "each Similar row must expose a ⤢ preview button"
        assert btn.text() == _icons.lightbox_icon, (
            "the affordance uses icons.lightbox_icon (⤢), distinct from the caret"
        )
        btn.click()

        assert emitted == [(["a", "b"], 1, "Origin Title")], (
            f"left-click must emit similar_preview_requested with ids/index/origin; got {emitted}"
        )

    def test_right_click_path_still_present(self, qapp):
        """The name button keeps its custom-context-menu (right-click → lightbox) path."""
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QPushButton
        from metatv.core.config import Config
        from metatv.gui.details_similar import _SimilarSection

        section = _SimilarSection(Config())
        section.load([_version(channel_id="a", name="Alpha")], origin_title="Origin")
        row = section._body_layout.itemAt(0).widget()

        # Find the name button (the wide, custom-context-menu one).
        name_btn = None
        for b in row.findChildren(QPushButton):
            if b.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu and "Alpha" in b.text():
                name_btn = b
                break
        assert name_btn is not None, (
            "the name button must keep the CustomContextMenu (right-click → lightbox) path"
        )
