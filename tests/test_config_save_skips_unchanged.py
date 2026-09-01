"""``Config.save()`` must not rewrite 129 KB when nothing changed.

Owner: *"this constant writing is brutal."* There are **130** ``config.save()``
call sites and, before this, not one of them checked whether anything had
changed — so every "on change" handler that fired without a change paid the
full cost on the UI thread. Their log shows the shape of it: six full writes in
sixteen seconds from nothing but walking the Settings list.

Measured on a copy of the owner's real config (299 keys, 129 KB):

===========================  =========
a save that writes            16.3 ms
a save with nothing changed    0.3 ms
===========================  =========

and in their running app, where it competes with everything else, the log
shows **55-93 ms** per write.

**The correctness argument is the deep copy.** Twenty-six sites mutate a config
container IN PLACE — ``config.x.append(...)``, ``config.x[k] = v`` — instead of
reassigning the field. A dirty flag hung off ``__setattr__`` would not see any
of them and would silently drop the user's edit. Comparing a fresh
``model_dump()`` against a deep copy of the last write sees the real state
whichever way it was written, which is why that is the design here.
"""
from __future__ import annotations

import pytest
import yaml

from metatv.core.config import Config


@pytest.fixture()
def cfg(tmp_path):
    c = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
               cache_dir=tmp_path / "cache")
    c.save()                      # establish the baseline
    return c


def _writes(cfg, monkeypatch) -> list:
    """Count how many times the expensive serialisation actually runs."""
    calls: list[int] = []
    real = yaml.dump

    def _counted(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr("metatv.core.config.yaml.dump", _counted)
    return calls


def test_an_unchanged_save_does_not_serialise(cfg, monkeypatch):
    calls = _writes(cfg, monkeypatch)
    cfg.save()
    cfg.save()
    cfg.save()
    assert calls == [], (
        f"{len(calls)} full serialisations for three saves that changed nothing")


def test_a_changed_field_still_writes(cfg, monkeypatch):
    """Non-degeneracy: the skip must not swallow a real change."""
    calls = _writes(cfg, monkeypatch)
    cfg.sidebar_width = 999
    cfg.save()
    assert len(calls) == 1
    on_disk = yaml.safe_load((cfg.config_dir / "config.yaml").read_text())
    assert on_disk["sidebar_width"] == 999


def test_an_in_place_container_mutation_still_writes(cfg, monkeypatch):
    """THE case a __setattr__ dirty flag would lose.

    26 sites in the app do exactly this rather than reassigning the field.
    If the snapshot aliased the live list, this comparison would be the list
    against itself, the save would be skipped, and the edit would vanish.
    """
    calls = _writes(cfg, monkeypatch)
    cfg.discover_hidden_shelves.append("genre:Action")
    cfg.save()

    assert len(calls) == 1, "an in-place append was treated as no change"
    on_disk = yaml.safe_load((cfg.config_dir / "config.yaml").read_text())
    assert on_disk["discover_hidden_shelves"] == ["genre:Action"], (
        "the in-place edit never reached disk")


def test_an_in_place_dict_write_still_writes(cfg, monkeypatch):
    """Same again for the ``config.x[k] = v`` form, which is also used."""
    calls = _writes(cfg, monkeypatch)
    cfg.sidebar_section_states["alerts"] = {"collapsed": True}
    cfg.save()
    assert len(calls) == 1
    on_disk = yaml.safe_load((cfg.config_dir / "config.yaml").read_text())
    assert on_disk["sidebar_section_states"]["alerts"] == {"collapsed": True}


def test_the_snapshot_is_not_an_alias_of_the_live_state(cfg):
    """Directly: mutating the live list must not mutate the record of the write."""
    cfg.discover_hidden_shelves.append("genre:Drama")
    assert cfg._last_written["discover_hidden_shelves"] == [], (
        "the snapshot aliases the live list, so nothing will ever look changed")


def test_force_writes_even_when_unchanged(cfg, monkeypatch):
    calls = _writes(cfg, monkeypatch)
    cfg.save(force=True)
    assert len(calls) == 1


def test_a_deleted_file_is_rewritten_even_though_nothing_changed(cfg, monkeypatch):
    """Existence is the other half of "already written".

    Without this the in-memory snapshot still matches, so a config deleted out
    from under the app would never be recreated and nobody would notice until
    the next launch came up default.
    """
    (cfg.config_dir / "config.yaml").unlink()
    calls = _writes(cfg, monkeypatch)
    cfg.save()
    assert len(calls) == 1, "a missing config file was not rewritten"
    assert (cfg.config_dir / "config.yaml").exists()


def test_the_first_save_always_writes(tmp_path, monkeypatch):
    """No snapshot yet means no basis to skip."""
    c = Config(config_dir=tmp_path / "config", data_dir=tmp_path / "data",
               cache_dir=tmp_path / "cache")
    calls: list[int] = []
    real = yaml.dump
    monkeypatch.setattr("metatv.core.config.yaml.dump",
                        lambda *a, **kw: (calls.append(1), real(*a, **kw))[1])
    c.save()
    assert len(calls) == 1


def test_model_dump_does_not_alias_live_containers(cfg):
    """The property the whole skip depends on — pinned, not assumed.

    ``save()`` keeps its ``model_dump()`` as the record of the last write and
    compares the next dump against it. That is only sound because a dump
    returns FRESH containers: if it handed back the live lists, the snapshot
    would alias them, every later comparison would be a list against itself,
    and **every save would be skipped**.

    Written after a mutation check embarrassed an earlier version of this
    file: swapping ``copy.deepcopy(data)`` for ``dict(data)`` changed nothing
    and no test noticed, because the protection was never the copy — it was
    this. A guard for the real invariant is worth more than a copy defending
    against a thing that cannot happen.
    """
    live_list = cfg.discover_hidden_shelves
    live_dict = cfg.sidebar_section_states
    dumped = cfg.model_dump()

    assert dumped["discover_hidden_shelves"] is not live_list, (
        "model_dump() aliases the live list — the last-written snapshot would "
        "track live state and no save would ever fire again")
    assert dumped["sidebar_section_states"] is not live_dict, (
        "model_dump() aliases a live dict — same failure, one level down")

    live_list.append("genre:Horror")
    assert dumped["discover_hidden_shelves"] == [], (
        "an in-place edit reached a dump taken before it")
