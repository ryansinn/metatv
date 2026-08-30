"""A server that answers and refuses is not a server you could not reach.

Every non-2xx response was reported as ``UNREACHABLE`` under the headline
"Couldn't reach the stream". For a 405 that is not merely imprecise, it is
backwards: the DNS resolved, the TCP connection opened, and the server sent a
status line. It is up. It just refused the request the probe made.

The owner hit exactly that — a 405 on a series stream, reported as unreachable,
with no cause and no next step. The verdict pointed at their network when the
answer was their provider.
"""

from __future__ import annotations

from unittest.mock import patch

import requests

from metatv.core import stream_diagnostics as sd


class _Resp:
    """Minimal stand-in for a streaming requests.Response."""

    def __init__(self, status: int):
        self.status_code = status

    def iter_content(self, chunk_size=0):        # pragma: no cover - not reached
        return iter(())

    def close(self):
        pass


def _run(status: int):
    with patch.object(sd.requests, "get", return_value=_Resp(status)):
        return sd.run_stream_diagnostic("http://host/live/u/p/1.ts")


def test_a_refused_stream_is_not_reported_as_unreachable():
    """The reported bug, at the verdict level."""
    result = _run(405)
    assert result.verdict == sd.REFUSED, (
        f"HTTP 405 produced {result.verdict!r} — the server answered, so this "
        f"is a refusal, not a failure to reach it"
    )
    assert result.verdict != sd.UNREACHABLE
    assert result.reachable is True, (
        "reachable=False for a server that sent us a status line"
    )
    assert result.http_status == 405


def test_the_summary_names_a_cause_and_a_next_step():
    """A verdict the user cannot act on is not a diagnostic."""
    summary = _run(405).summary
    assert "405" in summary
    lowered = summary.lower()
    assert "refus" in lowered, f"no cause named in {summary!r}"
    # It must say something the user can DO, not just what happened.
    assert any(w in lowered for w in ("try", "check", "stop", "wait", "refresh")), (
        f"no next step offered in {summary!r}"
    )


def test_each_common_status_gets_its_own_explanation():
    """403, 404 and 405 are different problems with different answers.

    Collapsing them into one message is the same defect as collapsing them
    into UNREACHABLE, one level down.
    """
    seen = {}
    for status in (401, 403, 404, 405, 429, 500):
        text = sd.explain_http_status(status)
        assert str(status) in text
        seen[status] = text
    assert len(set(seen.values())) == len(seen), (
        "two statuses share an explanation; they need different actions"
    )
    # 404 is "gone", not "refused" — the user should refresh, not retry.
    assert "no longer" in seen[404].lower()
    # 403 is most often the connection limit, which is actionable right now.
    assert "connection limit" in seen[403].lower()


def test_an_unknown_status_still_explains_itself():
    """No status may produce an empty or placeholder message."""
    text = sd.explain_http_status(418)
    assert "418" in text
    assert len(text) > 40


def test_a_real_connection_failure_is_still_unreachable():
    """The distinction only works if the other side stays intact."""
    with patch.object(sd.requests, "get",
                      side_effect=requests.ConnectionError("no route")):
        result = sd.run_stream_diagnostic("http://host/live/u/p/1.ts")
    assert result.verdict == sd.UNREACHABLE
    assert result.reachable is False
    assert result.http_status is None


def test_a_refusal_recommends_no_buffer_change():
    """No cache setting talks a server out of a 403."""
    profile, prebuffer = sd.recommend_buffer_profile(sd.REFUSED)
    assert profile is None and prebuffer is False


def test_every_verdict_the_core_can_emit_has_a_headline():
    """Derived from the module, so a new verdict cannot ship without one.

    The dialog maps verdict -> headline in a hand-written dict and falls back
    to the generic "Diagnostic complete". A verdict added without a headline
    therefore does not fail — it silently renders the generic string, which is
    exactly how a real answer turns into a shrug.
    """
    from metatv.gui.diagnostics_dialog import _HEADLINES

    verdicts = {
        getattr(sd, name) for name in dir(sd) if name.startswith("VERDICT_")
    }
    assert verdicts, "no VERDICT_* constants found — the derivation broke"
    missing = sorted(v for v in verdicts if v not in _HEADLINES)
    assert not missing, (
        f"verdict(s) {missing} would render the generic fallback headline"
    )


def test_the_credentials_never_reach_the_summary():
    """The explanation must not undo the redaction."""
    with patch.object(sd.requests, "get", return_value=_Resp(403)):
        result = sd.run_stream_diagnostic(
            "http://host/live/secretuser/secretpass/1.ts"
        )
    assert "secretuser" not in result.summary
    assert "secretpass" not in result.summary
    assert "secretpass" not in (result.error or "")
