"""Where a download lands, and when the disk says stop.

Both settled in "Catch, Keep, Record" (2026-08-30), feature 2.

Layout — *"Option A default, Option B as a choice — plus the per-item fallback:
an item whose metadata cannot fill the tree lands flat rather than in
Series/Unknown/Season 00/."* The fallback is the load-bearing part: most of
this library's VOD has thin metadata, and a tree built from guesses is worse
than a flat folder.

Space — *"a free-space floor, with a setting for what happens when it is hit:
stop immediately, or finish the current download and then stop. 'Finish the
current one' needs the remaining bytes to fit inside the floor, so it is a real
check, not a preference — if it does not fit, it stops immediately whatever the
setting says, and the row says so."*
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from metatv.core.download_naming import (
    LAYOUT_FLAT, LAYOUT_TREE, MediaFacts, facts_from_channel, relative_path,
)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def test_a_movie_files_under_movies_with_its_year():
    facts = MediaFacts(name="EN| Dune Part Two 4K", title="Dune Part Two",
                       year=2024, quality="4K")
    assert relative_path(facts, ".mkv") == Path("Movies/Dune Part Two (2024) - 4K.mkv")


def test_an_episode_files_under_series_show_season():
    facts = MediaFacts(name="EN| Severance S02E01", title="Severance",
                       season=2, episode=1)
    assert relative_path(facts, ".mkv") == Path(
        "Series/Severance/Season 02/Severance - S02E01.mkv")


def test_a_year_is_required_before_a_movie_may_enter_the_tree():
    """``Dune Part Two.mkv`` and ``Dune Part Two (2024).mkv`` are different
    claims to a scanner, and the yearless one matches the wrong film."""
    facts = MediaFacts(name="EN| Some Film HD", title="Some Film")
    assert relative_path(facts, ".mkv") == Path("Some Film.mkv")
    assert "Movies" not in str(relative_path(facts, ".mkv"))


def test_thin_metadata_falls_back_flat_never_to_an_invented_folder():
    """The whole point of the settled fallback.

    Asserted as a property rather than one string: ANY invented placeholder
    directory is the failure, not just the ``Unknown``/``Season 00`` spelling
    the artifact happened to name.
    """
    for facts in (MediaFacts(name="Raw Provider Name"),
                  MediaFacts(name="x", title="Half Known"),
                  MediaFacts(name="x", title="Show", season=3)):  # episode missing
        path = relative_path(facts, ".mkv")
        assert len(path.parts) == 1, f"{facts} was filed into {path}"
        assert "Unknown" not in str(path) and "Season 00" not in str(path)


def test_flat_layout_puts_everything_in_one_folder():
    facts = MediaFacts(name="x", title="Severance", season=2, episode=1)
    path = relative_path(facts, ".mkv", LAYOUT_FLAT)
    assert path == Path("Severance - S02E01.mkv")
    assert len(path.parts) == 1


def test_flat_names_prefer_the_derived_title_over_the_raw_provider_name():
    """The raw name carries the source prefix and quality tags — exactly the
    noise a filename should not have."""
    facts = MediaFacts(name="EN| FHD Dune Part Two 2024", title="Dune Part Two",
                       year=2024)
    assert relative_path(facts, ".mkv", LAYOUT_FLAT) == Path("Dune Part Two (2024).mkv")


@pytest.mark.parametrize("raw", ['A:B/C\\D*E?', "trailing dots...", "   ", ""])
def test_no_component_can_carry_a_separator_or_break_a_filesystem(raw):
    path = relative_path(MediaFacts(name="x", title=raw, year=1999), ".mkv")
    component = path.name
    assert "/" not in component and "\\" not in component
    assert not component.startswith(" ") and not component.startswith(".")
    assert component.endswith(".mkv") and len(component) > len(".mkv")


def test_facts_come_from_stored_columns_never_from_a_reparse():
    """``detected_*`` is computed once at ingestion; naming READS it.

    A channel whose stored title disagrees with its raw name proves which one
    is being used — if this ever started re-parsing, it would return the raw
    name's words instead.
    """
    channel = SimpleNamespace(
        name="EN| FHD The Wrong Words 2001", detected_title="Right Words",
        detected_year=2024, detected_season=None, detected_episode=None,
        detected_quality="FHD")
    facts = facts_from_channel(channel)
    assert facts.title == "Right Words"
    assert relative_path(facts, ".mkv") == Path("Movies/Right Words (2024) - FHD.mkv")


# ---------------------------------------------------------------------------
# destination_for — the enqueue seam
# ---------------------------------------------------------------------------

def _db(tmp_path):
    from metatv.core.database import Database

    db = Database(f"sqlite:///{tmp_path / 'dl.db'}")
    db.create_tables()
    return db


def _config(tmp_path, **over):
    base = {"download_dir": str(tmp_path / "lib"),
            "download_layout": LAYOUT_TREE,
            "download_free_space_floor_gb": 0.0,
            "download_space_policy": "finish_current"}
    base.update(over)
    return SimpleNamespace(**base)


def test_destination_for_reads_the_channel_and_builds_the_tree(tmp_path):
    from metatv.core.database import ChannelDB
    from metatv.core.download_manager import destination_for

    db = _db(tmp_path)
    with db.session_scope() as session:
        session.add(ChannelDB(id="c1", source_id="s", provider_id="p",
                              name="EN| Severance S02E01",
                              detected_title="Severance",
                              detected_season=2, detected_episode=1))
    with db.session_scope(commit=False) as session:
        dest = destination_for(session, _config(tmp_path), "c1",
                               "EN| Severance S02E01", "http://x/y/1.mkv")
    assert dest.match("Series/Severance/Season 02/Severance - S02E01.mkv")


def test_destination_for_survives_a_download_whose_channel_is_gone(tmp_path):
    """A queue row can outlive its channel. Losing the row must not fail the
    enqueue — it just means there is nothing to build a tree from."""
    from metatv.core.download_manager import destination_for

    db = _db(tmp_path)
    with db.session_scope(commit=False) as session:
        dest = destination_for(session, _config(tmp_path), "missing",
                               "Some Film", "http://x/y/1.mp4")
    assert dest.name == "Some Film.mp4"


def test_the_transfer_creates_the_tree_directories(tmp_path):
    """``library_dir`` only makes the root. Without this the first tree-layout
    download dies on FileNotFoundError opening Movies/….part."""
    import inspect

    from metatv.core.download_manager import DownloadManager

    source = inspect.getsource(DownloadManager._transfer)
    assert "parent.mkdir(parents=True" in source, (
        "nothing creates the destination directory — a tree layout writes into "
        "Movies/ and Series/Show/Season NN/, none of which exist yet")


# ---------------------------------------------------------------------------
# The free-space floor
# ---------------------------------------------------------------------------

def _manager(tmp_path, monkeypatch, free_bytes, **cfg):
    import shutil as _shutil

    from metatv.core.download_manager import DownloadManager

    mgr = DownloadManager.__new__(DownloadManager)
    mgr._config = _config(tmp_path, **cfg)
    monkeypatch.setattr(
        _shutil, "disk_usage",
        lambda _p: SimpleNamespace(total=0, used=0, free=free_bytes))
    return mgr


GB = 1024 ** 3


def test_no_floor_configured_never_blocks(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch, free_bytes=1,
                   download_free_space_floor_gb=0)
    assert mgr._space_shortfall() is None
    assert mgr._space_shortfall(100 * GB) is None


def test_a_new_download_is_refused_below_the_floor(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch, free_bytes=5 * GB,
                   download_free_space_floor_gb=10)
    reason = mgr._space_shortfall()
    assert reason and "10 GB floor" in reason


def test_finish_current_is_honoured_only_when_the_rest_actually_fits(
        tmp_path, monkeypatch):
    """The settled distinction, and the reason this returns a reason string.

    20 GB free, a 10 GB floor: there is 10 GB of headroom. A download with 2 GB
    left finishes; one with 40 GB left stops NOW, whatever the setting says.
    """
    mgr = _manager(tmp_path, monkeypatch, free_bytes=20 * GB,
                   download_free_space_floor_gb=10,
                   download_space_policy="finish_current")
    assert mgr._space_shortfall(2 * GB) is None
    reason = mgr._space_shortfall(40 * GB)
    assert reason and "would take free space below" in reason


def test_stop_now_does_not_wait_for_the_current_download(tmp_path, monkeypatch):
    mgr = _manager(tmp_path, monkeypatch, free_bytes=20 * GB,
                   download_free_space_floor_gb=10,
                   download_space_policy="stop_now")
    reason = mgr._space_shortfall(2 * GB)
    assert reason and "reached your 10 GB floor" in reason


def test_an_unreadable_destination_does_not_block_every_download(
        tmp_path, monkeypatch):
    """A storage error is the storage layer's to report, not a reason to
    refuse work — otherwise one bad mount silently stops the queue."""
    import shutil as _shutil

    from metatv.core.download_manager import DownloadManager

    mgr = DownloadManager.__new__(DownloadManager)
    mgr._config = _config(tmp_path, download_free_space_floor_gb=10)

    def _boom(_p):
        raise OSError("no such device")

    monkeypatch.setattr(_shutil, "disk_usage", _boom)
    assert mgr._space_shortfall() is None
