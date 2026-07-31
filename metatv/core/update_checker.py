"""In-app update checker — polls GitHub Releases for a newer MetaTV build.

Design mirrors the other background managers (``SeriesMonitorManager`` etc.):

* Network I/O runs in a ``ThreadPoolExecutor(max_workers=1)`` — never on the
  Qt main thread.
* The worker marshals its result back to the main thread through a private
  ``pyqtSignal`` (``_result_ready``); the main-thread slot is the only place
  that touches ``config`` / emits the public signals.  No widgets or
  ``NotificationManager`` calls happen off-thread (Qt threading rule).
* Config-gated: automatic checks honour ``update_check_enabled`` and a 24 h
  throttle (``update_last_checked``); the "newer" banner respects
  ``update_skip_version``.  A **manual** check bypasses the enable/throttle
  gates and the skip-version suppression (the user explicitly asked).

The pure helpers (:func:`is_newer_version`, :func:`select_dmg_url`,
:func:`build_update_info`, :func:`fetch_latest_release`) are import-safe with no
Qt dependency so they can be unit-tested without an event loop or a real network.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

import metatv

# GitHub REST v3 "latest release" endpoint (unauthenticated — ~60 req/hr/IP,
# far more than a once-a-day check needs).
GITHUB_LATEST_RELEASE_URL = (
    "https://api.github.com/repos/ryansinn/metatv/releases/latest"
)
THROTTLE_HOURS = 24
_NETWORK_TIMEOUT = 10
_DOWNLOAD_TIMEOUT = 120

_SEMVER_RE = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?"
    r"(?:[-.](?P<pre>[0-9A-Za-z][0-9A-Za-z.-]*))?"
)


@dataclass(frozen=True)
class UpdateInfo:
    """Immutable result of a release check.

    Attributes:
        current: The running version (``metatv.__version__``).
        latest: The latest published version, ``v`` stripped (e.g. ``"0.11.0"``).
        is_newer: True when *latest* is strictly newer than *current*.
        release_url: Human-facing GitHub release page (``html_url``).
        dmg_url: Direct download URL of the ``.dmg`` asset matching the running
            architecture, or ``""`` if the release has no ``.dmg`` at all.
    """

    current: str
    latest: str
    is_newer: bool
    release_url: str
    dmg_url: str


# ── Pure version comparison ──────────────────────────────────────────────────

def _version_key(version: str) -> tuple:
    """Return a tuple that sorts by semantic-version precedence.

    Handles a leading ``v`` and a pre-release suffix (``-rc1``, ``.beta.2``).
    A final release sorts **above** any of its pre-releases (semver rule).
    Unparseable input yields the lowest possible key so it is never treated as
    "newer" than a real version (and never crashes the caller).
    """
    match = _SEMVER_RE.match((version or "").strip())
    if not match:
        return (0, 0, 0, 0, ())

    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch") or 0)
    pre = match.group("pre")

    if pre is None:
        # Rank 1 → a release outranks any pre-release with the same M.m.p.
        return (major, minor, patch, 1, ())

    # Rank 0 → pre-release. Compare dot/dash-separated identifiers: numeric
    # identifiers (tagged 0) rank below alphanumeric ones (tagged 1) per semver,
    # and the (int, ...) first element keeps comparisons type-safe.
    identifiers = tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"[.-]", pre)
        if part
    )
    return (major, minor, patch, 0, identifiers)


def is_newer_version(latest: str, current: str) -> bool:
    """Return True iff *latest* is a strictly newer version than *current*."""
    return _version_key(latest) > _version_key(current)


# ── Arch-aware asset selection ───────────────────────────────────────────────

def _running_arch_tokens() -> tuple[str, ...]:
    """Return dmg-filename arch tokens for the running machine, best match first.

    ``platform.machine()`` reports ``"arm64"`` on Apple Silicon and ``"x86_64"``
    on Intel Macs — exactly the tokens the release workflow bakes into the dmg
    names. A couple of common aliases are folded in so an unexpected report
    (e.g. ``"aarch64"``) still resolves to the right dmg.
    """
    machine = (platform.machine() or "").lower()
    aliases = {
        "arm64": ("arm64", "aarch64"),
        "aarch64": ("arm64", "aarch64"),
        "x86_64": ("x86_64", "amd64"),
        "amd64": ("x86_64", "amd64"),
    }
    return aliases.get(machine, (machine,) if machine else ())


def select_dmg_url(assets) -> str:
    """Pick the ``.dmg`` download URL matching the running architecture.

    A release now carries one dmg per arch (``…-arm64.dmg`` / ``…-x86_64.dmg``).
    Prefer the dmg whose filename contains the running-arch token; **fall back**
    to the first ``.dmg`` when none carries an arch token (older single-dmg
    releases, or an unexpected asset name). Returns ``""`` when the release has
    no ``.dmg`` asset at all.

    Args:
        assets: The ``assets`` list from a GitHub release JSON object.

    Returns:
        The chosen ``browser_download_url``, or ``""`` if there is no ``.dmg``.
    """
    dmg_assets: list[tuple[str, str]] = []
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").lower()
        if not name.endswith(".dmg"):
            continue
        url = str(asset.get("browser_download_url") or "")
        if url:
            dmg_assets.append((name, url))

    if not dmg_assets:
        return ""

    for token in _running_arch_tokens():
        if not token:
            continue
        for name, url in dmg_assets:
            if token in name:
                return url

    # No arch-matching dmg → fall back to the first .dmg found.
    return dmg_assets[0][1]


# ── Pure DTO construction / network fetch ────────────────────────────────────

def build_update_info(data: dict, current_version: str) -> Optional[UpdateInfo]:
    """Build an :class:`UpdateInfo` from a parsed GitHub release JSON object.

    Args:
        data: The decoded JSON of a GitHub "release" object.
        current_version: The running version to compare against.

    Returns:
        An :class:`UpdateInfo`, or ``None`` when the payload has no usable tag.
    """
    if not isinstance(data, dict):
        return None
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return None

    latest_display = tag.lstrip("vV")
    release_url = str(data.get("html_url") or "")

    dmg_url = select_dmg_url(data.get("assets"))

    return UpdateInfo(
        current=current_version,
        latest=latest_display,
        is_newer=is_newer_version(tag, current_version),
        release_url=release_url,
        dmg_url=dmg_url,
    )


def fetch_latest_release(
    current_version: str,
    *,
    url: str = GITHUB_LATEST_RELEASE_URL,
    timeout: int = _NETWORK_TIMEOUT,
) -> Optional[UpdateInfo]:
    """Fetch the latest release from GitHub and build an :class:`UpdateInfo`.

    Any network / decode failure is swallowed and returns ``None`` (silent
    no-op — an update check must never crash or block the app).
    """
    try:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"MetaTV/{current_version}",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug(f"Update check network/parse failure (ignored): {exc}")
        return None

    return build_update_info(data, current_version)


def download_dmg(dmg_url: str, dest_dir: Optional[Path] = None) -> Optional[str]:
    """Download the ``.dmg`` at *dmg_url* into *dest_dir* (default ~/Downloads).

    Returns the local file path on success, or ``None`` on any failure.
    """
    if not dmg_url:
        return None
    dest_dir = dest_dir or (Path.home() / "Downloads")
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = os.path.basename(urllib.parse.urlparse(dmg_url).path) or "MetaTV.dmg"
        dest = dest_dir / name
        request = urllib.request.Request(
            dmg_url, headers={"User-Agent": "MetaTV-Updater"}
        )
        with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response, \
                open(dest, "wb") as handle:
            shutil.copyfileobj(response, handle)
        logger.info(f"Downloaded update to {dest}")
        return str(dest)
    except (urllib.error.URLError, OSError) as exc:
        logger.warning(f"Update download failed: {exc}")
        return None


# ── Qt-facing checker ────────────────────────────────────────────────────────

class UpdateChecker(QObject):
    """Checks GitHub Releases for a newer version and surfaces the result.

    Signals (all delivered on the **main thread**):
        update_available(object): a newer, non-suppressed :class:`UpdateInfo`
            was found. The host shows the "download / skip / later" banner.
        no_update(object): a **manual** check finished with no newer version —
            payload is the :class:`UpdateInfo` (up-to-date) or ``None``
            (offline/error). Automatic checks stay silent here.
        download_completed(str): a ``.dmg`` download finished — the local path,
            or ``""`` on failure. The host reveals/opens it.

    Private signals marshal worker→main-thread results; never call them from UI.
    """

    update_available = pyqtSignal(object)   # UpdateInfo
    no_update = pyqtSignal(object)          # UpdateInfo | None (manual only)
    download_completed = pyqtSignal(str)    # local path, "" on failure

    _result_ready = pyqtSignal(object)      # (UpdateInfo | None, manual: bool)
    _download_ready = pyqtSignal(str)       # local path, "" on failure

    def __init__(self, config, current_version: Optional[str] = None, parent=None):
        """Initialise the checker.

        Args:
            config: The application ``Config`` (read for gates, written to record
                the last-checked timestamp / skip version — always on the main
                thread).
            current_version: Override for the running version; defaults to
                ``metatv.__version__``.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self.config = config
        self._current = current_version or metatv.__version__
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="update_check"
        )
        self._result_ready.connect(self._on_result)
        self._download_ready.connect(self.download_completed.emit)

    # -- public API -----------------------------------------------------------

    def check_async(self, *, manual: bool = False) -> None:
        """Kick a background release check.

        Automatic checks (``manual=False``) are gated by ``update_check_enabled``
        and the 24 h throttle; a manual check bypasses both.  Safe to call from
        the main thread; the network runs in the executor.
        """
        if not manual:
            if not getattr(self.config, "update_check_enabled", True):
                return
            if not self._throttle_ok():
                return
        self._executor.submit(self._worker_check, manual)

    def download_update(self, info: UpdateInfo) -> None:
        """Download *info*'s ``.dmg`` in the background (no-op if it has none)."""
        if not info or not info.dmg_url:
            return
        self._executor.submit(self._worker_download, info.dmg_url)

    def shutdown(self) -> None:
        """Stop the executor (registered in the closeEvent cleanup registry)."""
        self._executor.shutdown(wait=False)

    # -- gating ---------------------------------------------------------------

    def _throttle_ok(self) -> bool:
        """Return True when the last automatic check was ≥ 24 h ago (or never)."""
        last = getattr(self.config, "update_last_checked", "") or ""
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
        except ValueError:
            return True
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - last_dt >= timedelta(hours=THROTTLE_HOURS)

    # -- workers (background thread) ------------------------------------------

    def _worker_check(self, manual: bool) -> None:
        info = fetch_latest_release(self._current)
        self._result_ready.emit((info, manual))

    def _worker_download(self, dmg_url: str) -> None:
        path = download_dmg(dmg_url)
        self._download_ready.emit(path or "")

    # -- main-thread slot -----------------------------------------------------

    def _on_result(self, payload) -> None:
        """Handle a worker result on the main thread: record + route to signals."""
        info, manual = payload

        # Record the check time (main-thread config write) so the throttle works
        # regardless of outcome.
        try:
            self.config.update_last_checked = datetime.now(timezone.utc).isoformat()
            self.config.save()
        except Exception as exc:  # pragma: no cover - config save is best-effort
            logger.debug(f"Could not persist update_last_checked: {exc}")

        if info is None:
            if manual:
                self.no_update.emit(None)
            return

        if info.is_newer:
            if manual:
                self.update_available.emit(info)
            elif info.latest != (getattr(self.config, "update_skip_version", "") or ""):
                self.update_available.emit(info)
            # else: auto check, user skipped this version → stay silent.
        elif manual:
            self.no_update.emit(info)
