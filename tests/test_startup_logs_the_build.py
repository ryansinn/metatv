"""The first log line must name the build that wrote it.

Owner, reading a pasted startup log: *"shouldn't the console log state which
version of MetaTV is being launched? it's kind of weird to omit that."*

It matters more under rolling releases than it would have before. Every push to
main ships to the tester, so "0.56.0" no longer distinguishes two builds a week
apart — and a log pasted into a bug report has to say which commit produced it
or the report cannot be checked out and reproduced.
"""

from __future__ import annotations

from metatv import __version__
from metatv.core.build_info import compose_title


def _startup_line() -> str:
    """Render the line exactly as ``setup_logging`` composes it."""
    from metatv.core.build_info import window_title

    return f"{window_title()} starting — v{__version__}"


def test_the_startup_line_names_the_version():
    assert __version__ in _startup_line()


def test_the_startup_line_names_the_build_not_just_the_version():
    """A version alone cannot identify a rolling build."""
    line = _startup_line()
    assert "MetaTV" in line
    # In a checkout that is branch + sha; in a packaged app it is the stamped
    # build id. Either way the line must carry more than the bare version.
    assert line.replace(__version__, "").strip(" v—-"), (
        "the line carries nothing but the version"
    )


def test_setup_logging_actually_emits_it():
    """Execute it — a composed string that never reaches a logger is not a log.

    Captures through loguru rather than asserting on source text, so the test
    fails if the call is removed, moved behind a condition, or logged at a level
    the default configuration filters out.

    No home-directory patching: the autouse ``_isolate_user_config`` fixture
    already points ``Path.home()`` at a tmp dir, so the log files this writes
    land there rather than in the real ``~/.config/metatv/logs``.
    """
    from loguru import logger

    import metatv.__main__ as entry

    seen: list[str] = []
    sink_id = logger.add(lambda m: seen.append(str(m)), level="INFO")
    try:
        entry.setup_logging()
        logger.info("probe")
    finally:
        logger.remove(sink_id)

    starting = [m for m in seen if "starting" in m]
    assert starting, "setup_logging emitted no startup line at INFO"
    assert __version__ in starting[0], (
        f"the startup line does not name the version: {starting[0]!r}"
    )


def test_a_packaged_build_reports_its_stamped_id():
    """With no git, the title falls back to the stamped build id.

    That is the case that matters most: the tester runs a packaged app, where
    there is no branch or sha to fall back on.
    """
    title = compose_title(sha="", dirty=False, pr="", branch="",
                          version="0.56.0+20260829.a3e7a28")
    assert "0.56.0+20260829.a3e7a28" in title


def test_a_dirty_checkout_is_marked_as_such():
    """An asterisk, so a log from modified code cannot be read as a clean build."""
    clean = compose_title(sha="a3e7a28", dirty=False, pr="", branch="main")
    dirty = compose_title(sha="a3e7a28", dirty=True, pr="", branch="main")
    assert "*" not in clean
    assert "*" in dirty
