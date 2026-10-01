"""The Flatpak build: what the app does inside one, and what the manifest grants.

The bundle is built and launched in CI (.github/workflows/flatpak.yml); these
tests cover what that smoke run cannot see — the update button's behaviour in
the sandbox, and that the manifest's folder grants still match the paths the
app actually reads. Those paths come from ``Path.home()``, not ``$XDG_*``, so a
missing grant makes the app start with an empty library rather than fail.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import yaml

from metatv.core.config import Config
from metatv.core.runtime_env import flatpak_app_id
from metatv.gui.main_window_updates import _UpdatesMixin

_ROOT = Path(__file__).resolve().parent.parent
_FLATPAK = _ROOT / "packaging" / "flatpak"
_MANIFEST = _FLATPAK / "io.github.ryansinn.MetaTV.yml"


def _manifest() -> dict:
    return yaml.safe_load(_MANIFEST.read_text())


def test_flatpak_app_id_reads_the_sandbox_env(monkeypatch) -> None:
    monkeypatch.setenv("FLATPAK_ID", "io.github.ryansinn.MetaTV")
    assert flatpak_app_id() == "io.github.ryansinn.MetaTV"
    monkeypatch.delenv("FLATPAK_ID")
    assert flatpak_app_id() is None


def _updates_host() -> SimpleNamespace:
    return SimpleNamespace(notification_manager=MagicMock(), update_checker=MagicMock())


def test_manual_update_check_inside_flatpak_points_at_the_bundle(monkeypatch) -> None:
    """The checker only knows .dmg assets — inside the sandbox it must not run."""
    monkeypatch.setenv("FLATPAK_ID", "io.github.ryansinn.MetaTV")
    host = _updates_host()
    _UpdatesMixin._manual_update_check(host)
    host.update_checker.check_async.assert_not_called()
    shown = host.notification_manager.show.call_args.kwargs
    assert "Flatpak" in shown["title"]
    assert "MetaTV.flatpak" in shown["message"]


def test_manual_update_check_outside_flatpak_still_checks(monkeypatch) -> None:
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    host = _updates_host()
    _UpdatesMixin._manual_update_check(host)
    host.update_checker.check_async.assert_called_once_with(manual=True)


def test_manifest_grants_every_folder_the_app_reads() -> None:
    """Each default data path must sit under a granted folder."""
    grants = {
        a.split("=", 1)[1].split(":")[0]
        for a in _manifest()["finish-args"] if a.startswith("--filesystem=")
    }
    xdg = {"xdg-config": ".config", "xdg-data": ".local/share",
           "xdg-cache": ".cache", "xdg-videos": "Videos"}
    granted = {xdg[g.split("/", 1)[0]] + "/" + g.split("/", 1)[1] for g in grants}

    defaults = Config()
    needed = [
        ".config/metatv",                                   # config.yaml, logs
        ".local/share/metatv",                              # metatv.db
        defaults.deep_cache_dir.removeprefix("~/"),         # ~/.cache/metatv/deepcache
        defaults.download_dir.removeprefix("~/"),           # downloads + Recordings/
    ]
    for path in needed:
        assert any(path == g or path.startswith(g + "/") for g in granted), (
            f"~/{path} is read by the app but not granted in {_MANIFEST.name}")


def test_manifest_base_app_matches_the_runtime() -> None:
    """The PyQt BaseApp is built against one KDE runtime; a mismatch won't build."""
    m = _manifest()
    assert m["base-version"] == m["runtime-version"]


def test_files_the_manifest_installs_exist() -> None:
    for name in ("metatv.sh", "io.github.ryansinn.MetaTV.desktop",
                 "io.github.ryansinn.MetaTV.metainfo.xml"):
        assert (_FLATPAK / name).is_file(), name
    assert (_ROOT / "packaging" / "icon" / "metatv.svg").is_file()
