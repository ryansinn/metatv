"""Saving the config must not cost 75ms of the UI thread.

From the owner's startup log — 57 seconds, with the app doing nothing but
starting:

    13 config saves
    1,807 ms of blocking file work   (3.2% of the window)
    one save took 577 ms
    five saves inside 1.1 seconds

``Config.save()`` is called from 127 places and every call re-serialises all
288 keys. Profiling the 75 ms showed where it goes:

    model_dump()            0.2 ms
    shutil.copy2 (backup)   0.1 ms
    yaml.dump()            69.0 ms     <- effectively all of it

So the fix is the emitter, not the backup and not pydantic. PyYAML ships a C
emitter when libyaml is present: 69.5 ms -> 12.2 ms on this file, with
identical parsed output.
"""

import pathlib

import pytest
import yaml

from metatv.core.config import QA_STATE_FILENAME, Config, _qa_defaults, _YamlDumper, _YamlLoader


def test_the_c_emitter_is_used_when_the_platform_has_it() -> None:
    """Not a hard requirement — libyaml is optional and CI may lack it."""
    if hasattr(yaml, "CSafeDumper"):
        assert _YamlDumper is yaml.CSafeDumper
        assert _YamlLoader is yaml.CSafeLoader
    else:  # pragma: no cover - depends on the build
        assert _YamlDumper is yaml.SafeDumper


def test_the_fallback_is_a_real_dumper() -> None:
    """A missing libyaml must degrade to slow, never to broken."""
    assert _YamlDumper in (getattr(yaml, "CSafeDumper", None), yaml.SafeDumper)
    assert callable(_YamlDumper)


def test_every_key_survives_a_write_and_read(tmp_path) -> None:
    """THE assertion. A faster emitter that dropped a key would be a disaster
    quietly — the config holds every setting, watchlist and saved recipe."""
    cfg = Config(config_dir=tmp_path)
    cfg.filter_adult_mode = "all"
    cfg.saved_recipes = [{"name": "R", "includes": {"genre": ["Drama"]}, "excludes": {}}]
    cfg.epg_watchlist_patterns = ["Denver Broncos", "Stargate SG-1"]
    expected = cfg.model_dump()

    cfg.save()
    # The state is now written across TWO files: config.yaml, and qa_state.yaml
    # for the qa_* fields (38% of a real config, and not configuration at all).
    # The invariant is unchanged and is exactly why this test matters — no key
    # may be silently lost — so it is checked across both, which also catches a
    # key that fell between them.
    raw = yaml.load((tmp_path / "config.yaml").read_text(encoding="utf-8"),
                    Loader=_YamlLoader)
    qa_file = tmp_path / QA_STATE_FILENAME
    if qa_file.exists():
        raw.update(yaml.load(qa_file.read_text(encoding="utf-8"),
                             Loader=_YamlLoader) or {})
    else:
        # No sidecar means no QA state was set, so those fields are at their
        # declared defaults — which is what `expected` holds for them.
        raw.update(_qa_defaults(Config))

    differing = []
    for key, value in expected.items():
        if isinstance(value, pathlib.Path):
            value = str(value)
        if raw.get(key) != value:
            differing.append(key)
    assert not differing, f"these keys did not survive the round trip: {differing}"


def test_both_emitters_produce_the_same_data(tmp_path) -> None:
    """They differ in line wrapping only; the parse must be identical.

    Checked against real content — non-ASCII collection names are exactly where
    the two emitters wrap differently.
    """
    if not hasattr(yaml, "CSafeDumper"):
        pytest.skip("libyaml not available on this build")

    data = {
        "collections": ["US| DIREC TV GO ᴴᴰ/ᴿᴬᵂ ⁶⁰ᶠᵖˢ", "Abc Alabama"],
        "patterns": ["Denver Broncos", "Séraphin: un homme et son péché"],
        "nested": {"a": [1, 2, 3], "b": {"c": True}},
    }
    pure = yaml.dump(data, Dumper=yaml.SafeDumper, default_flow_style=False)
    fast = yaml.dump(data, Dumper=yaml.CSafeDumper, default_flow_style=False)

    assert yaml.safe_load(pure) == yaml.safe_load(fast) == data


def test_a_saved_config_is_readable_by_the_loader(tmp_path) -> None:
    """End to end, through the real load path rather than a raw yaml read."""
    cfg = Config(config_dir=tmp_path)
    cfg.epg_watchlist_patterns = ["Mile High Football"]
    cfg.save()

    reread = yaml.load((tmp_path / "config.yaml").read_text(encoding="utf-8"),
                       Loader=_YamlLoader)
    assert reread["epg_watchlist_patterns"] == ["Mile High Football"]


def test_the_backup_is_still_written(tmp_path) -> None:
    """The backup costs 0.1ms and is the only recovery path — it stays."""
    cfg = Config(config_dir=tmp_path)
    cfg.save()
    cfg.epg_watchlist_patterns = ["changed"]
    cfg.save()

    assert (tmp_path / "config.yaml.bak").exists(), "the backup stopped being written"
