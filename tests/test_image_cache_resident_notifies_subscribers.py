"""IMG-3: a resident-cache hit must notify subscribe() callers, not only the
broadcast.

``discover_card.request_image`` deliberately uses ``subscribe()`` rather than
the ``image_loaded`` broadcast (#574's N-squared fix). ``_on_image_ready`` —
the DOWNLOAD path — dispatches to subscribers and then broadcasts. The
resident-LRU fast path in ``get_image_async`` only broadcast, so any card
whose poster was already resident was never told, kept its placeholder, and
kept its infinite shimmer animation running.

The owner saw exactly this: the details pane rendered a title's poster (it
uses the broadcast, and storing it made the pixmap resident) while the
Discover card for that same title stayed a placeholder forever.
"""
from PyQt6.QtGui import QPixmap

from metatv.core.image_cache import ImageCache


class _Subscriber:
    """A subscribe() caller. Must be a BOUND METHOD holder — subscribe keeps
    a WeakMethod, so a lambda would be collected immediately."""

    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.failed: list[str] = []

    def on_loaded(self, url: str, pixmap) -> None:
        self.loaded.append(url)

    def on_failed(self, url: str, error: str) -> None:
        self.failed.append(error)


def _resident_cache(tmp_path, url: str) -> ImageCache:
    """An ImageCache whose resident LRU already holds a real pixmap for *url*."""
    cache = ImageCache(cache_dir=str(tmp_path))
    pixmap = QPixmap(4, 4)
    pixmap.fill()
    cache._store_resident(url, pixmap)
    assert cache.get_image_resident(url) is not None, "precondition: url is resident"
    return cache


def test_resident_hit_notifies_the_subscriber(tmp_path, qapp):
    """The bug: a resident hit served only the broadcast, so a subscribed card
    was never told and stayed on its placeholder."""
    url = "https://image.tmdb.org/t/p/w154/poster.jpg"
    cache = _resident_cache(tmp_path, url)

    sub = _Subscriber()
    cache.subscribe(url, sub.on_loaded, sub.on_failed)
    cache.get_image_async(url)

    assert sub.loaded == [url], (
        "a resident-cache hit must reach subscribe() callers — a Discover card "
        "uses subscribe(), not the image_loaded broadcast"
    )
    assert sub.failed == [], "a resident hit is a success, never a failure"


def test_resident_hit_still_broadcasts(tmp_path, qapp):
    """The one-per-view listeners (details pane, lightbox, trail map) use the
    broadcast — fixing the subscriber path must not cost them their signal."""
    url = "https://image.tmdb.org/t/p/w154/poster.jpg"
    cache = _resident_cache(tmp_path, url)

    seen: list[str] = []
    cache.image_loaded.connect(lambda u, p: seen.append(u))
    cache.get_image_async(url)

    assert seen == [url], "the image_loaded broadcast must still fire on a resident hit"


def test_resident_hit_forgets_the_subscription(tmp_path, qapp):
    """Subscriptions are one-shot (``_dispatch`` pops them). A second request
    must not re-notify a subscriber that has already been served."""
    url = "https://image.tmdb.org/t/p/w154/poster.jpg"
    cache = _resident_cache(tmp_path, url)

    sub = _Subscriber()
    cache.subscribe(url, sub.on_loaded, sub.on_failed)
    cache.get_image_async(url)
    cache.get_image_async(url)

    assert sub.loaded == [url], "the subscription is one-shot; it must not fire twice"
