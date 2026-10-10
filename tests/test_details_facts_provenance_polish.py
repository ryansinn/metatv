"""Details facts: what the section says about WHERE each fact came from.

A source's own report is not a measurement (no ✓, no "Re-check"), a decade read
off a year in the title is deduced not guessed, and rows that only repeat the
Audio row are dropped. The probe button lives in the heading, left of the count.
"""
from datetime import datetime

from PyQt6.QtWidgets import QLabel

from metatv.core.config import Config
from metatv.core.repositories.dtos import ChannelTagDTO
from metatv.gui.details_facts import _DetailsSection

_INFO = {"video": {"codec": "h264", "profile": "High", "width": 720, "height": 406,
                   "fps": 25, "bitrate_kbps": 827},
         "audio": [{"lang": "eng", "codec": "aac", "channels": 2}], "subs": []}


def _section(owned_widgets, source):
    s = owned_widgets.own(_DetailsSection(Config()))
    s.set_copy(provider_name="TREX Shared", copy_code="EN")
    s._original_language = "English"
    s.load_tags([ChannelTagDTO("language", "English", True, 0.9, ("provider_probe",)),
                 ChannelTagDTO("decade", "2010s", False, 0.3, ("name_parse",))])
    s.load_stream_info({"info": _INFO, "source": source, "measured_at": datetime(2026, 10, 10)})
    return s


def _keys(s):
    return [lbl.text() for lbl in s._content.findChildren(QLabel)
            if lbl.text() and not lbl.text().startswith("·") and lbl.isVisibleTo(s)]


def test_a_source_report_is_not_called_checked(qapp, owned_widgets):
    s = _section(owned_widgets, "provider")
    assert s._probe_btn.text() == "Get stream details"
    assert s._probe_btn.parent() is s._header, "the probe button sits in the heading"


def test_a_probe_offers_a_recheck(qapp, owned_widgets):
    assert _section(owned_widgets, "probe")._probe_btn.text() == "Re-check stream"


def test_decade_is_deduced_and_repeat_rows_are_dropped(qapp, owned_widgets):
    s = _section(owned_widgets, "provider")
    from PyQt6.QtCore import QCoreApplication, QEvent
    # Replaced rows are deleteLater'd; flush them so only live rows are read.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    captions = [lbl.text() for lbl in s._content.findChildren(QLabel)
                if lbl.text().startswith("·")]
    assert "· deduced from title" in captions
    assert not any("guessed" in c for c in captions)
    keys = _keys(s)
    assert "Language" not in keys, "a Language row repeating the one audio track says nothing"
    assert "Original language" not in keys, "nor does an original language equal to it"
