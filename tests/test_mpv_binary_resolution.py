"""Tests for mpv-binary resolution (bundled-when-frozen vs dev PATH fallback).

Pins the invariant the packaging work depends on: a frozen ``.app`` prefers its
own vendored ``Resources/mpv/mpv``, an explicit ``$MPV_BINARY`` overrides, and
the ``shutil.which("mpv")`` fallback MUST remain for Linux dev + the test suite.
"""

from metatv.core.players import mpv as mpv_mod


def test_resolve_prefers_bundled_when_frozen(monkeypatch, tmp_path):
    """When frozen and a bundled mpv exists, its path is returned."""
    mpv_mod._reset_mpv_binary_cache()
    fake = tmp_path / "mpv" / "mpv"
    fake.parent.mkdir(parents=True)
    fake.write_text("#!/bin/sh\n")

    monkeypatch.setattr(mpv_mod, "is_frozen", lambda: True)
    monkeypatch.setattr(mpv_mod, "bundle_resource_path", lambda rel: tmp_path / rel)
    try:
        assert mpv_mod._resolve_mpv_binary() == str(fake)
    finally:
        mpv_mod._reset_mpv_binary_cache()


def test_resolve_falls_back_to_which_in_dev(monkeypatch):
    """Not frozen, no override → resolution is ``shutil.which('mpv')`` (unchanged)."""
    mpv_mod._reset_mpv_binary_cache()
    monkeypatch.setattr(mpv_mod, "is_frozen", lambda: False)
    monkeypatch.delenv("MPV_BINARY", raising=False)
    monkeypatch.setattr(
        mpv_mod.shutil, "which",
        lambda name: "/usr/bin/mpv" if name == "mpv" else None,
    )
    try:
        assert mpv_mod._resolve_mpv_binary() == "/usr/bin/mpv"
    finally:
        mpv_mod._reset_mpv_binary_cache()


def test_resolve_env_override_wins_over_path(monkeypatch, tmp_path):
    """``$MPV_BINARY`` takes precedence over the PATH lookup when set."""
    mpv_mod._reset_mpv_binary_cache()
    custom = tmp_path / "custom-mpv"
    custom.write_text("")

    monkeypatch.setattr(mpv_mod, "is_frozen", lambda: False)
    monkeypatch.setenv("MPV_BINARY", str(custom))
    # which() would return a different binary; the env override must still win.
    monkeypatch.setattr(mpv_mod.shutil, "which", lambda name: "/usr/bin/mpv")
    try:
        assert mpv_mod._resolve_mpv_binary() == str(custom)
    finally:
        mpv_mod._reset_mpv_binary_cache()


def test_resolve_caches_result(monkeypatch):
    """Resolution is cached — a second call does not re-probe."""
    mpv_mod._reset_mpv_binary_cache()
    calls: list[str] = []

    def _which(name):
        calls.append(name)
        return "/usr/bin/mpv"

    monkeypatch.setattr(mpv_mod, "is_frozen", lambda: False)
    monkeypatch.delenv("MPV_BINARY", raising=False)
    monkeypatch.setattr(mpv_mod.shutil, "which", _which)
    try:
        first = mpv_mod._resolve_mpv_binary()
        second = mpv_mod._resolve_mpv_binary()
        assert first == second == "/usr/bin/mpv"
        assert len(calls) == 1  # cached after the first resolution
    finally:
        mpv_mod._reset_mpv_binary_cache()
