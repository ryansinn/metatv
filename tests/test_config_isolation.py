"""Guard: the test suite must never write the developer's real user config.

Root cause of a recurring, destructive bug: ``Config.config_dir`` defaults to
``Path.home()/.config/metatv`` and ``Config.save()`` writes there, so any test
that built a default ``Config()`` and saved (e.g. ``test_epg_on_now_display``'s
On-Now header-state test) silently overwrote the real ``~/.config/metatv/
config.yaml`` — wiping Global Exclusions, the What's-New cursor, and the
migration version fields. The running app then re-ran migrations, re-showed old
What's New, and lost the user's curation.

The autouse ``_isolate_user_config`` fixture in ``conftest.py`` redirects
``Path.home()`` to a throwaway tmp dir. These tests fail if that guard regresses.
"""

from pathlib import Path


def test_config_dir_is_isolated_to_tmp():
    """A default Config must resolve under pytest's tmp home, not the real one."""
    from metatv.core.config import Config

    cfg = Config()
    assert "pytest" in str(cfg.config_dir), (
        f"Config is NOT isolated from the real user dir: {cfg.config_dir} — the "
        "autouse _isolate_user_config fixture in conftest.py has regressed"
    )


def test_saving_a_default_config_stays_in_tmp():
    """Config().save() must land under the tmp home — never the real ~/.config."""
    from metatv.core.config import Config

    cfg = Config()
    cfg.save()
    written = cfg.config_dir / "config.yaml"
    assert written.exists(), "save() should have written a config file"
    assert "pytest" in str(written), (
        f"save() escaped isolation and wrote {written} — would clobber real config"
    )
