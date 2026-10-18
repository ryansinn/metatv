"""config.yaml stops carrying the folders ``app_paths`` derives.

``config_dir`` / ``data_dir`` / ``database_url`` were written on every save, so
the file was a second copy of where things live — and ``config_dir`` was stored
inside the folder it names. They are now written only when they differ from
the derived default (a custom data folder), and a stale stored ``config_dir``
is ignored. Runs under ``conftest``'s ``Path.home()`` isolation, so
``app_paths`` points into a tmp dir.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from metatv.core import app_paths
from metatv.core.config import Config

_PATH_KEYS = ("config_dir", "data_dir", "database_url")


def _on_disk() -> dict:
    return yaml.safe_load((app_paths.config_dir() / "config.yaml").read_text(encoding="utf-8"))


def test_a_default_install_writes_none_of_the_derived_paths():
    config, _ = Config.load()
    config.save(force=True)
    assert not [k for k in _PATH_KEYS if k in _on_disk()]


def test_an_old_file_loads_with_its_paths_and_sheds_them_on_the_next_save():
    config, _ = Config.load()
    config.save(force=True)
    data = _on_disk()
    data.update(config_dir="/somewhere/stale", data_dir=str(app_paths.data_dir()),
                database_url=f"sqlite:///{app_paths.data_dir() / 'metatv.db'}")
    (app_paths.config_dir() / "config.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")

    loaded, recovered = Config.load()
    assert not recovered, "a file with database_url is valid, not corrupt"
    assert loaded.config_dir == app_paths.config_dir(), "a stored config_dir must not redirect saves"
    loaded.save(force=True)
    assert not [k for k in _PATH_KEYS if k in _on_disk()]


def test_a_custom_data_folder_survives_the_prune(tmp_path):
    config, _ = Config.load()
    custom = tmp_path / "elsewhere"
    config.data_dir = custom
    config.database_url = f"sqlite:///{custom / 'metatv.db'}"
    config.save(force=True)
    assert Path(_on_disk()["data_dir"]) == custom
    assert Config.load()[0].database_url == f"sqlite:///{custom / 'metatv.db'}"


def test_loading_the_pruned_file_does_not_rewrite_it_as_stale():
    config, _ = Config.load()
    config.save(force=True)
    assert Config.load()[0]._rewrite_if_stale(_on_disk(), Path("config.yaml")) is False
