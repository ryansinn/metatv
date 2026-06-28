"""Regression test — the "FILTERED VARIANTS" header stylesheet must parse.

The header's QSS was built across an f-string line and a *plain* string line; the
plain line used ``}}`` (correct only inside an f-string), so the rendered QSS had
a stray extra ``}`` — Qt logged "Could not parse stylesheet of object
QPushButton" and dropped the header styling.  This pins that the rendered
stylesheet has balanced braces (i.e. is parseable).
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_filtered_variants_header_stylesheet_is_parseable(qapp):
    from metatv.core.config import Config
    from metatv.gui.details_versions import _VersionSection

    vs = _VersionSection(Config())
    ss = vs._filtered_hdr_lbl.styleSheet()

    assert "}}" not in ss, f"double closing brace breaks QSS parse: {ss!r}"
    assert ss.count("{") == ss.count("}"), (
        f"unbalanced braces make the stylesheet unparseable: {ss!r}"
    )
