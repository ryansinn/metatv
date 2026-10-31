"""Adding a source happens in the Sources editor, and a failed test never sticks.

The owner, on the macOS build: a source with a wrong username/password failed
its test (correctly), but after the credentials were corrected the dialog kept
failing instantly until the app was relaunched. ``AddProviderDialog`` is gone —
every Add Source button now opens the editor on a blank source — so the
sequence that must work is this one, driven on the real editor against a real
local server (CI runs it on macOS as well as Linux):

    wrong credentials -> test fails, Add stays disabled
    right credentials -> test passes, Add enables
    Add               -> the source exists, with what was on the form

A hostname, not 127.0.0.1, so name resolution runs as it does for a provider.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from metatv.core.database import ProviderDB

GOOD_PASSWORD = "p&ss#1+ok"   # characters that break an unescaped query string


class _Xtream(BaseHTTPRequestHandler):
    def log_message(self, *_a):  # quiet
        pass

    def do_GET(self):  # noqa: N802 (http.server API)
        q = parse_qs(urlparse(self.path).query)
        ok = q.get("password", [""])[0] == GOOD_PASSWORD
        body = {"user_info": {"auth": 1 if ok else "0", "status": "Active",
                              "exp_date": "1900000000", "max_connections": "1",
                              "active_cons": "0"}, "server_info": {}}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


@pytest.fixture(scope="module")
def server_url():
    srv = HTTPServer(("127.0.0.1", 0), _Xtream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://localhost:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def editor(qapp, db, owned_widgets):
    from metatv.gui.provider_editor import ProviderEditorView

    ed = owned_widgets.own(ProviderEditorView(db))
    ed.start_new_source()
    return ed


def _run_test(qapp, ed) -> None:
    done = []
    ed._test_connection()
    ed._test_thread.all_done.connect(lambda r: done.append(r))
    end = time.time() + 20
    while not done and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert done, "the connection test never finished"
    qapp.processEvents()


def test_a_new_source_shows_only_what_a_new_source_has(editor):
    assert editor._save_btn.text() == "Add Source"
    assert not editor._save_btn.isEnabled(), "Add must wait for a passing test"
    assert editor._discard_btn.text() == "Cancel"
    for w in (editor._delete_btn, editor._action_refresh_btn,
              editor._action_toggle_btn):
        assert w.isHidden(), f"{w.text()!r} belongs to an existing source"


def test_wrong_then_right_credentials_can_be_added(qapp, db, editor, server_url):
    """THE regression: a failed test must not poison the next one."""
    added = []
    editor.provider_added.connect(lambda pid, epg: added.append((pid, epg)))
    editor._new_url_input.setText(server_url)          # typed, not yet added
    editor._username_input.setText("user")
    editor._password_input.setText("wrong")

    _run_test(qapp, editor)
    assert not editor._save_btn.isEnabled(), "a rejected login enabled Add"

    editor._password_input.setText(GOOD_PASSWORD)
    _run_test(qapp, editor)
    assert editor._save_btn.isEnabled(), "corrected credentials still fail the test"

    editor._name_input.setText("Fixed Source")
    editor._save_btn.click()
    assert len(added) == 1
    with db.session_scope(commit=False) as session:
        prov = session.query(ProviderDB).filter_by(id=added[0][0]).one()
        assert prov.name == "Fixed Source"
        assert prov.password == GOOD_PASSWORD
        assert prov.url == server_url
        assert prov.icon, "a new source gets an icon"


def test_editing_credentials_after_a_pass_needs_a_new_test(qapp, editor, server_url):
    editor._new_url_input.setText(server_url)
    editor._username_input.setText("user")
    editor._password_input.setText(GOOD_PASSWORD)
    _run_test(qapp, editor)
    assert editor._save_btn.isEnabled()

    editor._password_input.setText(GOOD_PASSWORD + "x")
    assert not editor._save_btn.isEnabled(), "the pass was for other credentials"

    editor._password_input.setText(GOOD_PASSWORD)
    editor._name_input.setText("Renamed")                # a name is not a credential
    assert not editor._save_btn.isEnabled()


@pytest.mark.parametrize("epg", [True, False])
def test_add_keeps_the_forms_settings(qapp, db, editor, epg):
    editor._new_url_input.setText("http://host.example:8080")
    editor._add_url()
    editor._new_url_input.setText("http://backup.example:8080")
    editor._add_url()
    editor._epg_enabled_check.setChecked(epg)
    editor._new_tested_ok = True          # the gate is covered above; this is the write
    added = []
    editor.provider_added.connect(lambda pid, e: added.append((pid, e)))
    editor._add_new_source()

    pid, emitted_epg = added[0]
    assert emitted_epg is epg
    with db.session_scope(commit=False) as session:
        prov = session.query(ProviderDB).filter_by(id=pid).one()
        assert bool(prov.epg_enabled) is epg
        assert prov.name == "host.example", "an unnamed source is named after its host"
        assert [u["url"] for u in prov.urls] == ["http://host.example:8080",
                                                 "http://backup.example:8080"]


def test_removing_an_address_from_a_new_source_just_removes_it(editor):
    for u in ("http://a.example", "http://b.example"):
        editor._new_url_input.setText(u)
        editor._add_url()
    editor._remove_url(0)
    assert [pu.url for pu in editor._provider_urls] == ["http://b.example"]
    editor._remove_url(0)       # no "at least one URL" rule before anything is saved
    assert editor._provider_urls == []


def test_every_add_source_button_opens_the_editor():
    from unittest.mock import MagicMock

    from metatv.gui.main_window import MainWindow

    host = MagicMock()
    MainWindow.add_provider(host)
    host.switch_to_sources_manager.assert_called_once()
    host.sources_manager_view.start_new_source.assert_called_once()


@pytest.mark.parametrize("value,granted", [
    (1, True), ("1", True), (True, True), ("true", True),
    (0, False), ("0", False), ("false", False), ("", False), (None, False),
])
def test_auth_values_servers_send(value, granted):
    from metatv.core.provider_probe import auth_granted
    assert auth_granted(value) is granted


@pytest.mark.parametrize("count,guided", [(0, True), (2, False), (None, False)])
def test_launch_with_no_source_opens_the_add_form(qapp, count, guided):
    """No source at all -> the Sources screen on a blank source; a read error is not 'none'."""
    from unittest.mock import MagicMock

    from metatv.gui.main_window import MainWindow

    host = MagicMock()
    host.__dict__["sources_strip"] = None
    host._refresh_details_provider_map.return_value = count
    MainWindow.load_providers(host)
    qapp.processEvents()
    assert host._guide_to_first_source.called is guided


def test_the_guide_runs_once_per_session(qapp):
    """Deleting the last source later must not yank the user to the Sources screen."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from metatv.gui.main_window import MainWindow

    host = SimpleNamespace(add_provider=MagicMock())
    MainWindow._guide_to_first_source(host)
    MainWindow._guide_to_first_source(host)
    assert host.add_provider.call_count == 1
