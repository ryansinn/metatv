"""A poster arriving must not wake every card that is waiting for one.

Owner: *"scrolling through poster/grid view of Discover … into space where the
posters haven't been loaded and the system becomes unresponsive … scrolling
back into content with posters is smooth."*

``image_loaded`` is a BROADCAST on the shared cache. Every card awaiting a
poster connected to it, so each arriving image invoked the slot on ALL waiting
cards and all but one returned immediately on a url mismatch. Filling a screen
of posters cost N² dispatches — measured at 157 ms of pure signal plumbing for
800 cards, before decoding a single pixel.

The asymmetry in the report is the tell: a card DISCONNECTS once its image
lands, so scrolling back over loaded posters left the fan-out empty and felt
fine, while scrolling into unloaded space rebuilt it.
"""

import tempfile

import pytest
from PyQt6.QtGui import QPixmap

from metatv.core.image_cache import ImageCache


@pytest.fixture
def cache(qapp):
    return ImageCache(cache_dir=tempfile.mkdtemp())


class _Card:
    """Stands in for a Discover card waiting on one poster."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.loaded: list[str] = []
        self.failed: list[str] = []

    def on_loaded(self, url: str, pixmap) -> None:
        self.loaded.append(url)

    def on_failed(self, url: str, error: str) -> None:
        self.failed.append(error)


# ── routing ─────────────────────────────────────────────────────────────────

def test_an_image_reaches_only_the_card_that_asked_for_it(cache, qapp) -> None:
    """THE fix. Pre-fix every waiting card's slot ran for every image."""
    a, b = _Card("http://x/a.jpg"), _Card("http://x/b.jpg")
    cache.subscribe(a.url, a.on_loaded, a.on_failed)
    cache.subscribe(b.url, b.on_loaded, b.on_failed)

    cache._dispatch(a.url, 0, a.url, QPixmap(1, 1))

    assert a.loaded == [a.url]
    assert b.loaded == [], "an unrelated card was woken for someone else's image"


def test_two_cards_wanting_the_same_poster_both_get_it(cache, qapp) -> None:
    """The same title can appear on two shelves — routing must not mean 'one'."""
    url = "http://x/shared.jpg"
    one, two = _Card(url), _Card(url)
    cache.subscribe(url, one.on_loaded)
    cache.subscribe(url, two.on_loaded)

    cache._dispatch(url, 0, url, QPixmap(1, 1))

    assert one.loaded == [url] and two.loaded == [url]


def test_a_subscription_fires_once_and_is_forgotten(cache, qapp) -> None:
    """Otherwise the fan-out would grow for the life of the session."""
    card = _Card("http://x/a.jpg")
    cache.subscribe(card.url, card.on_loaded)

    cache._dispatch(card.url, 0, card.url, QPixmap(1, 1))
    cache._dispatch(card.url, 0, card.url, QPixmap(1, 1))

    assert card.loaded == [card.url], "the subscription survived its own delivery"


def test_a_failure_reaches_only_its_own_card(cache, qapp) -> None:
    a, b = _Card("http://x/a.jpg"), _Card("http://x/b.jpg")
    cache.subscribe(a.url, a.on_loaded, a.on_failed)
    cache.subscribe(b.url, b.on_loaded, b.on_failed)

    cache._dispatch(a.url, 1, a.url, "boom")

    assert a.failed == ["boom"] and b.failed == []


# ── it must not resurrect a destroyed card ──────────────────────────────────

def test_a_card_destroyed_mid_download_is_skipped(cache, qapp) -> None:
    """Scrolling away destroys cards while their posters are still in flight.

    Holding the callback strongly would keep dead widgets alive and then raise
    RuntimeError when the underlying C++ object had already gone — the failure
    mode CLAUDE.md calls out for ``__new__``'d QObjects. WeakMethod means a
    dead card is simply skipped.
    """
    fired: list[str] = []

    class _Doomed:
        """Records into a list that OUTLIVES it, so we can see if it ran."""

        def on_loaded(self, url, pixmap):
            fired.append(url)

    card = _Doomed()
    cache.subscribe("http://x/a.jpg", card.on_loaded)
    del card

    import gc
    gc.collect()

    cache._dispatch("http://x/a.jpg", 0, "http://x/a.jpg", QPixmap(1, 1))

    assert fired == [], (
        "a destroyed card's callback still ran — the cache is holding it "
        "strongly, which keeps dead widgets alive and raises RuntimeError once "
        "the underlying C++ object is gone"
    )


# ── the property the whole change exists for ────────────────────────────────

def test_delivery_cost_does_not_grow_with_the_number_of_waiting_cards(cache, qapp) -> None:
    """Linear, not quadratic.

    Asserts the SHAPE rather than a millisecond figure — a wall-clock threshold
    would be a flaky gate on a busy CI box. Under the old broadcast every card
    was invoked for every image, so total invocations were N²; now each image
    reaches exactly its own subscribers.
    """
    invocations = 0

    class _Counting(_Card):
        def on_loaded(self, url, pixmap):
            nonlocal invocations
            invocations += 1
            super().on_loaded(url, pixmap)

    n = 300
    cards = [_Counting(f"http://x/{i}.jpg") for i in range(n)]
    for c in cards:
        cache.subscribe(c.url, c.on_loaded)

    px = QPixmap(1, 1)
    for c in cards:
        cache._dispatch(c.url, 0, c.url, px)

    assert invocations == n, (
        f"{n} images woke {invocations} callbacks — the broadcast fan-out is back "
        f"(a quadratic dispatch would be {n * n:,})"
    )
    assert all(c.loaded for c in cards), "some card never received its poster"
