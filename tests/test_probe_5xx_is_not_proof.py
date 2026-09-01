"""A server error on the validation probe must not block playback.

Owner, 2026-09-01: *"the 500 error didn't matter, I chose play anyway and it
played. So there's something wrong with flagging the 500 error."*

``validate_stream_url`` failed anything ``>= 400``, so a 500 produced a warning
prompt in front of a stream that plays perfectly. Three things make that wrong:

* The method's OWN docstring says IPTV servers return spurious 5xx.
* On an account capped at one connection — all of the owner's providers report
  ``max_connections = 1`` — this probe is itself a SECOND connection. The
  provider answers it 500 precisely because it is already serving something.
* mpv is the better authority: it reconnects
  (``--stream-lavf-o=reconnect=1``), and when a stream really is dead the
  failure path surfaces the real error.

A prompt that cries wolf on a working stream is worse than no prompt, because
it trains the user to click through the one that matters.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class _Resp:
    """Minimal stand-in for a streamed ``requests`` response."""

    def __init__(self, status: int, body: bytes = b""):
        self.status_code = status
        self.headers = {"Content-Type": "video/mp2t"}
        self._body = body

    def iter_content(self, chunk_size=256):
        if self._body:
            yield self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _validate(status: int, body: bytes = b""):
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    with patch("metatv.gui.main_window_streaming.requests.get",
               return_value=_Resp(status, body)):
        return _StreamingMixin.validate_stream_url(host, "http://x/y.ts")


@pytest.mark.parametrize("status", [500, 502, 503, 504, 429])
def test_a_server_error_does_not_block_playback(status):
    """The reported bug: a 500 flagged a stream that plays."""
    ok, err = _validate(status)
    assert ok is True, (
        f"HTTP {status} blocked playback — the probe is a second connection on "
        f"a one-connection account, so this says nothing about the stream")
    assert err is None


@pytest.mark.parametrize("status", [401, 403, 404, 410, 511])
def test_a_client_error_is_still_reported(status):
    """Being told 'no' is different from the server having a moment.

    These stay reported so the user sees them — the caller still offers
    "Play Anyway", which is what makes a 511 shared-account cap recoverable.
    """
    ok, err = _validate(status)
    assert ok is False
    assert err == f"HTTP {status}"


def test_a_healthy_response_still_validates():
    """Non-degeneracy: this must not have become 'always True'."""
    ok, err = _validate(200, b"\x47" + b"\x00" * 255)   # MPEG-TS sync byte
    assert ok is True and err is None


def test_an_empty_body_is_still_a_failure():
    """A 200 with no data is a real failure and must stay one."""
    ok, err = _validate(200, b"")
    assert ok is False
