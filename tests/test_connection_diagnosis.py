"""When every address fails, the app must say WHY, not just how many.

Owner, after losing an evening to it: adding a new source failed on every URL,
and the cause was a VPN exit whose IP the provider blocks. The editor showed
five red badges and nothing else. The probe layer already knew the difference
between "the host answered and refused you" and "nothing answered" — nobody was
asking it.

These tests pin the distinction that actually changes what a user does next.
"""

import pytest

from metatv.core.connection_diagnosis import Diagnosis, diagnose
from metatv.core.provider_probe import ProbeResult, ProbeStatus


def _r(status: ProbeStatus, detail: str = "", success: bool = False) -> ProbeResult:
    return ProbeResult(url="http://h", success=success, latency_ms=1,
                       status=status, detail=detail)


# ── the distinction that matters ────────────────────────────────────────────

def test_every_host_refusing_is_not_a_network_problem() -> None:
    """403 everywhere means the addresses WORK. Saying "unreachable" sends the
    user to fix DNS when the answer is their VPN endpoint."""
    report = diagnose([_r(ProbeStatus.HTTP_ERROR, "403"),
                       _r(ProbeStatus.HTTP_ERROR, "403")])
    assert report.diagnosis is Diagnosis.REFUSED_BY_HOST
    assert report.refusal_codes == ("403",)


def test_nothing_answering_is_not_a_refusal() -> None:
    """The mirror image, and the reason a single bucket would be useless."""
    report = diagnose([_r(ProbeStatus.TIMEOUT), _r(ProbeStatus.ERROR, "DNS")])
    assert report.diagnosis is Diagnosis.UNREACHABLE
    assert report.refusal_codes == ()


@pytest.mark.parametrize("detail", ["403", "HTTP 403", "403 Forbidden", "status=403"])
def test_the_refusal_code_is_found_however_the_caller_spelled_it(detail: str) -> None:
    """Call sites store the code bare and decorated. Pinning one spelling means
    the guard silently stops recognising refusals the day that phrasing moves."""
    assert diagnose([_r(ProbeStatus.HTTP_ERROR, detail)]).diagnosis is Diagnosis.REFUSED_BY_HOST


def test_an_account_verdict_outranks_a_refusal_code() -> None:
    """A server that names the account state has answered the question.

    Both signals are present here. Reporting "your IP is blocked" when the
    provider has said the subscription is dead sends the user to change VPN
    endpoints forever.
    """
    report = diagnose([_r(ProbeStatus.INACTIVE, "Expired"),
                       _r(ProbeStatus.HTTP_ERROR, "403")])
    assert report.diagnosis is Diagnosis.SUBSCRIPTION_INACTIVE


def test_rejected_credentials_are_named_as_such() -> None:
    report = diagnose([_r(ProbeStatus.AUTH_FAILED), _r(ProbeStatus.TIMEOUT)])
    assert report.diagnosis is Diagnosis.CREDENTIALS_REJECTED


# ── it must stay quiet when it has nothing to add ───────────────────────────

def test_one_working_address_produces_no_diagnosis() -> None:
    """A partial failure is NORMAL — it is what several addresses are for.

    Announcing it would train the user to ignore the panel, which is how the
    real warning gets missed.
    """
    report = diagnose([_r(ProbeStatus.ACTIVE, success=True), _r(ProbeStatus.TIMEOUT)])
    assert report.diagnosis is Diagnosis.NONE


def test_no_addresses_produces_no_diagnosis() -> None:
    assert diagnose([]).diagnosis is Diagnosis.NONE


def test_a_non_refusal_http_error_is_not_read_as_a_block() -> None:
    """500 is the provider's own fault, not a statement about the caller."""
    assert diagnose([_r(ProbeStatus.HTTP_ERROR, "500")]).diagnosis is not Diagnosis.REFUSED_BY_HOST


def test_mixed_causes_are_reported_as_mixed() -> None:
    report = diagnose([_r(ProbeStatus.HTTP_ERROR, "500"), _r(ProbeStatus.TIMEOUT)])
    assert report.diagnosis is Diagnosis.MIXED


def test_the_report_carries_its_evidence() -> None:
    """The UI quotes the codes, so a verdict is checkable rather than magic."""
    report = diagnose([_r(ProbeStatus.HTTP_ERROR, "403"), _r(ProbeStatus.HTTP_ERROR, "405")])
    assert report.total == 2
    assert report.refusal_codes == ("403", "405")
    assert report.counts[ProbeStatus.HTTP_ERROR] == 2


# ── core stays English-free ─────────────────────────────────────────────────

def test_core_returns_no_prose() -> None:
    """``provider_probe`` opens by promising no user-facing English in core, so
    a headless backend can reuse it and a translation can exist later. A
    sentence leaking into the report would quietly break that."""
    report = diagnose([_r(ProbeStatus.HTTP_ERROR, "403")])
    for value in (report.diagnosis.value, *report.refusal_codes):
        assert " " not in value, f"{value!r} reads like prose, not a token"


# ── the editor actually renders it ──────────────────────────────────────────

def test_the_editor_shows_the_advice_and_hides_it_when_a_url_works(qtbot) -> None:
    """Drives the real slot on a real QLabel.

    A data-only test would pass for a diagnosis nobody can see — the whole
    defect being fixed is that the information existed and never reached the
    screen.
    """
    from PyQt6.QtWidgets import QLabel

    from metatv.gui.provider_editor import ProviderEditorView

    host = ProviderEditorView.__new__(ProviderEditorView)
    host._diagnosis_lbl = QLabel()
    qtbot.addWidget(host._diagnosis_lbl)

    ProviderEditorView._on_diagnosis(
        host, diagnose([_r(ProbeStatus.HTTP_ERROR, "403"),
                        _r(ProbeStatus.HTTP_ERROR, "403")])
    )
    shown = host._diagnosis_lbl.text()
    assert "VPN" in shown, f"the blocked-IP case must name the likely cause: {shown!r}"
    assert "403" in shown, "the evidence must be quoted so the verdict is checkable"
    assert host._diagnosis_lbl.isVisibleTo(host._diagnosis_lbl.parentWidget() or
                                           host._diagnosis_lbl)

    # One address working is normal; the panel must go away entirely.
    ProviderEditorView._on_diagnosis(
        host, diagnose([_r(ProbeStatus.ACTIVE, success=True), _r(ProbeStatus.TIMEOUT)])
    )
    assert host._diagnosis_lbl.isHidden(), "panel stayed up when a URL worked"


def test_every_diagnosis_the_core_can_return_has_phrasing() -> None:
    """A new Diagnosis member with no entry would render a blank panel.

    Derived from the enum rather than a hand-listed set, so the day someone
    adds a category this fails instead of shipping an empty box.
    """
    from metatv.gui.provider_editor import _DIAGNOSIS_TEXT

    missing = [
        d.name for d in Diagnosis
        if d is not Diagnosis.NONE and d not in _DIAGNOSIS_TEXT
    ]
    assert not missing, f"no user-facing text for: {missing}"
