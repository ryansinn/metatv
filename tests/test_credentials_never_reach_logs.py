"""No log sink ever sees a subscription credential.

An Xtream stream URL embeds the account's username and password in its path —
``{base}/movie/{user}/{pass}/{id}.ext`` — and ``player_api.php`` takes the same
pair as ``?username=…&password=…``. Seventy-one call sites across the app log a
URL. The file sink runs at DEBUG with seven-day retention.

A scan of one developer machine found **26,793 ``username=`` and 26,761
``password=`` occurrences** already written to ``~/.config/metatv/logs/`` from
ordinary use, plus 385 path-shaped stream URLs.

``_redact`` existed the whole time. ``main_window_streaming.py`` imported it at
line 22 and called it at one of its five URL logs. That is the shape of every
enumeration failure this codebase has hit: the sweep is real, and it covers what
somebody remembered.

So the guarantee is at the SINK, not at the call sites, and these tests hold
that line — including the one that matters most, which is that a newly written
``logger.info(f"...{url}")`` is safe from an author who has never heard of any
of this.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest
from loguru import logger

from metatv.core.stream_diagnostics import _redact

SECRET = "hunter2s3cret"
USER = "joe_subscriber"


@pytest.fixture
def sink():
    """A real loguru file sink with the app's patcher installed."""
    path = pathlib.Path(tempfile.mkdtemp()) / "test.log"
    logger.remove()
    logger.configure(patcher=lambda r: r.__setitem__("message", _redact(r["message"])))
    sink_id = logger.add(path, level="DEBUG")
    yield path
    logger.remove(sink_id)
    logger.configure(patcher=None)


@pytest.mark.parametrize("template", [
    "  URL: http://host.tv:8080/movie/{u}/{p}/12345.mp4",
    "  URL: http://host.tv:8080/live/{u}/{p}/9.ts",
    "Trying: http://host.tv:8080/series/{u}/{p}/77.mkv",
    "fetching http://host.tv/player_api.php?username={u}&password={p}&action=get_vod",
    "GET http://host.tv/xmltv.php?username={u}&password={p}",
    "Stream URL: http://host.tv/{u}/{p}/321.ts",
    "failover to http://b.host.tv:8080/movie/{u}/{p}/12345.mp4?token={p}",
])
def test_no_shape_of_credential_url_reaches_the_sink(sink, template):
    """Every shape the app actually logs, through a real sink."""
    logger.info(template.format(u=USER, p=SECRET))
    body = sink.read_text()
    assert SECRET not in body, f"password written to the log: {body.strip()}"
    assert USER not in body, f"username written to the log: {body.strip()}"


def test_a_brand_new_call_site_is_covered_without_knowing_it(sink):
    """The property the whole design rests on.

    Somebody adding a URL log tomorrow will not call ``_redact`` — the author
    of the five sites in ``main_window_streaming.py`` didn't, four times, while
    importing it. The patcher means they don't have to.
    """
    url = f"http://host.tv:8080/movie/{USER}/{SECRET}/999.mp4"
    logger.debug(f"some future diagnostic nobody has written yet: {url}")
    assert SECRET not in sink.read_text()


def test_every_severity_is_patched(sink):
    """A patcher applies per record, so an exception path must be covered too —
    and error paths are exactly where people log the full URL."""
    url = f"http://host.tv/player_api.php?username={USER}&password={SECRET}"
    for emit in (logger.debug, logger.info, logger.warning, logger.error):
        emit(f"failed against {url}")
    body = sink.read_text()
    assert SECRET not in body
    assert body.count("password=***") == 4


def test_redaction_keeps_the_url_useful(sink):
    """A redactor that destroyed the host would get switched off.

    The reason to log the URL is to see which host and which stream id failed;
    both survive.
    """
    logger.info(f"URL: http://host.tv:8080/movie/{USER}/{SECRET}/12345.mp4")
    body = sink.read_text()
    assert "host.tv:8080" in body
    assert "12345.mp4" in body


def test_non_credential_text_is_untouched(sink):
    """No false positives — an over-eager redactor makes logs useless."""
    logger.info("Loaded 492,511 channels from provider TREX in 41.2s")
    assert "Loaded 492,511 channels from provider TREX in 41.2s" in sink.read_text()


def test_the_app_wiring_actually_redacts(tmp_path):
    """Run the app's OWN setup_logging() and read the file it really writes.

    This replaces a structural check that could not fail. It asserted three
    substrings of ``inspect.getsource(app_main)``::

        assert "logger.configure(patcher=" in source
        assert "_redact" in source
        assert source.index("logger.configure(patcher=") < source.index("logger.add(")

    Every one of those survives the removal of the redaction itself. Replacing
    the patcher body with ``record["message"] = record["message"]`` leaves the
    ``configure`` call in place, leaves the ordering intact, and leaves
    ``_redact`` in the source — because ``__main__`` still IMPORTS it on line
    11. A dead import kept the guard green while credentials went to disk. Run
    against that mutant, this file passed 12 of 12.

    The old docstring called the structural form deliberate: *"the alternative
    is booting the real app and reading its log"*. That was the wrong pair of
    options. ``setup_logging()`` is an ordinary function — no Qt, no window, no
    event loop — so the real wiring can simply be CALLED, which is what happens
    here. The conftest ``_isolate_user_config`` fixture already points
    ``Path.home()`` at a tmp dir, so the sink lands under *tmp_path*'s sibling
    and never touches the developer's own logs.
    """
    from metatv import __main__ as app_main
    from metatv.core.log_paths import active_log_file

    url = f"http://box.example:8080/movie/{USER}/{SECRET}/1234.mkv"
    api = f"http://box.example:8080/player_api.php?username={USER}&password={SECRET}"

    logger.remove()
    try:
        app_main.setup_logging()
        # Written the way an author who has never heard of _redact writes it.
        logger.info(f"GET {url}")
        logger.error(f"failed {api}")
        logger.complete()

        written = active_log_file().read_text(encoding="utf-8", errors="replace")
    finally:
        logger.remove()
        logger.configure(patcher=None)

    assert SECRET not in written, "the password reached the app's real log file"
    assert USER not in written, "the username reached the app's real log file"
    # Redaction has to leave the record diagnosable, or people turn it off.
    assert "box.example" in written, "the host was scrubbed away with the secret"


def test_the_patcher_is_installed_before_the_sink():
    """Ordering still deserves a check: a sink added first sees raw records.

    Kept structural because it is a statement about the ORDER of two lines,
    which has no runtime signature once both have run — but it is now the only
    structural assertion here, and the behavioural test above is what proves
    redaction actually happens.
    """
    import inspect

    from metatv import __main__ as app_main

    source = inspect.getsource(app_main)
    assert source.index("logger.configure(patcher=") < source.index("logger.add("), (
        "the patcher is installed AFTER the file sink, so early records leak"
    )
