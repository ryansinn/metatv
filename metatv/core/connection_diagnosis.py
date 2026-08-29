"""Turn a set of failed URL probes into a single machine-readable verdict.

Why this exists
---------------
When every URL of a source fails, the editor used to show one red badge per
URL and nothing else. Owner, after an evening lost to it: setting up a new
source failed on every address, and the actual cause was a VPN endpoint whose
IP the provider blocks. Nothing on screen pointed there — and the distinction
matters, because "the server refused you" and "nothing answered" call for
opposite actions.

The probe layer already knows enough to tell them apart; nobody was asking it.
A ``403``/``405`` means the host ANSWERED and declined, so DNS, routing and the
address are all fine and the problem is *who you appear to be*. A timeout means
the opposite. An ``INACTIVE`` account status means the server looked you up and
said the subscription is not live — no amount of address-fiddling helps.

UI-free, deliberately
---------------------
This module returns a :class:`Diagnosis` enum and the counts behind it. It does
NOT return a sentence. ``provider_probe`` opens by promising exactly that — no
user-facing presentation, no English in ``core`` — so a headless backend can
reuse it and a translation can exist later. Rendering lives in the GUI.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from metatv.core.provider_probe import ProbeResult, ProbeStatus

#: HTTP statuses that mean "the host answered and refused you". A provider
#: returns these when the calling IP is blocked (a VPN exit node shared with
#: abusers is the common case) or when the subscription no longer entitles the
#: request. Both are about the CALLER, never about the address being wrong —
#: which is why they must not be read as "this host is unreliable".
REFUSAL_STATUSES: frozenset[str] = frozenset({"403", "405", "401", "429"})


class Diagnosis(str, Enum):
    """Why every URL failed, as a category the UI can phrase."""

    SUBSCRIPTION_INACTIVE = "subscription_inactive"
    CREDENTIALS_REJECTED = "credentials_rejected"
    REFUSED_BY_HOST = "refused_by_host"
    UNREACHABLE = "unreachable"
    MIXED = "mixed"
    NONE = "none"


@dataclass(frozen=True)
class DiagnosisReport:
    """A verdict plus the evidence for it.

    Attributes:
        diagnosis: The category.
        total: How many URLs were probed.
        refusal_codes: Distinct HTTP refusal codes seen, sorted — evidence the
            UI can quote so the verdict is checkable rather than magic.
        counts: Probe status -> how many URLs ended that way.
    """

    diagnosis: Diagnosis
    total: int
    refusal_codes: tuple[str, ...]
    counts: dict[ProbeStatus, int]


def _refusal_code(result: ProbeResult) -> str | None:
    """The HTTP refusal code in *result*, if it is one.

    ``detail`` carries the status code for ``HTTP_ERROR`` (documented on
    ``ProbeResult``). It is matched as a substring rather than compared whole
    because callers have historically stored it both bare ("403") and decorated
    ("HTTP 403", "403 Forbidden") — pinning the exact spelling would make this
    silently stop recognising refusals the first time that phrasing changed.
    """
    if result.status is not ProbeStatus.HTTP_ERROR:
        return None
    detail = result.detail or ""
    return next((code for code in sorted(REFUSAL_STATUSES) if code in detail), None)


def diagnose(results: Sequence[ProbeResult]) -> DiagnosisReport:
    """Explain why none of *results* succeeded.

    Ordered by how much the evidence actually settles, not by severity. A
    server that names the account state has told us the answer outright; a
    refusal code narrows it to the caller; a timeout only says "nothing came
    back", which is the weakest signal and therefore the last resort.

    Args:
        results: Probe results for every configured URL. A sequence containing
            any success returns :attr:`Diagnosis.NONE` — this only explains a
            total failure, and a partial failure is normal (that is what having
            several addresses is FOR).

    Returns:
        The verdict and its evidence.
    """
    counts = Counter(r.status for r in results)
    total = len(results)

    if not results or any(r.success for r in results):
        return DiagnosisReport(Diagnosis.NONE, total, (), dict(counts))

    codes = tuple(sorted({c for c in (_refusal_code(r) for r in results) if c}))

    # The server looked the account up and reported on it. Nothing about the
    # address or the network is in question.
    if counts[ProbeStatus.INACTIVE]:
        return DiagnosisReport(Diagnosis.SUBSCRIPTION_INACTIVE, total, codes, dict(counts))
    if counts[ProbeStatus.AUTH_FAILED]:
        return DiagnosisReport(Diagnosis.CREDENTIALS_REJECTED, total, codes, dict(counts))

    # Every host answered, and every one declined. The addresses work; the
    # caller is the problem — a blocked IP being much the most common reason.
    if codes and counts[ProbeStatus.HTTP_ERROR] == total:
        return DiagnosisReport(Diagnosis.REFUSED_BY_HOST, total, codes, dict(counts))

    # Nothing answered anywhere. DNS, routing, or the connection itself.
    if counts[ProbeStatus.TIMEOUT] + counts[ProbeStatus.ERROR] == total:
        return DiagnosisReport(Diagnosis.UNREACHABLE, total, codes, dict(counts))

    return DiagnosisReport(Diagnosis.MIXED, total, codes, dict(counts))
