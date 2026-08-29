"""User-facing phrasing for a connection diagnosis.

``core.connection_diagnosis`` returns a category and its evidence, and
deliberately no prose — ``provider_probe`` opens by promising no English in
``core`` so a headless backend can reuse it and a translation can exist later.
The sentences live here.

Its own module rather than sitting in ``provider_editor``: that file is the
dialog, and a table of copy is a different concern that would have pushed it
79 lines past its code-health limit. Splitting by what the code IS, not to
satisfy the number.
"""

from __future__ import annotations

from metatv.core.connection_diagnosis import Diagnosis

#: What to tell the user for each diagnosis, and what to suggest doing.
#:
#: Core returns a category; the sentences are here because ``core`` is
#: deliberately English-free (see ``provider_probe``'s module docstring).
#: Each entry is (headline, what to try) — the second half is the part that was
#: missing, and the reason an evening went into a VPN endpoint nobody suspected.
_DIAGNOSIS_TEXT: dict[Diagnosis, tuple[str, str]] = {
    Diagnosis.REFUSED_BY_HOST: (
        "Every address answered and refused the connection.",
        "The addresses and your network are fine — the provider is rejecting "
        "who you appear to be. This is most often a VPN exit whose IP the "
        "provider blocks: try switching VPN endpoint, or turning the VPN off. "
        "An expired subscription can also do this.",
    ),
    Diagnosis.SUBSCRIPTION_INACTIVE: (
        "The provider says this subscription is not active.",
        "The addresses work and your credentials were recognised, so changing "
        "them will not help. Check the subscription with the provider.",
    ),
    Diagnosis.CREDENTIALS_REJECTED: (
        "The provider rejected the username or password.",
        "Re-enter the credentials exactly as the provider supplied them, "
        "watching for trailing spaces.",
    ),
    Diagnosis.UNREACHABLE: (
        "Nothing answered at any address.",
        "This looks like a network problem rather than an account one: check "
        "you are online, and if a VPN is connected, try it off or on another "
        "endpoint. A DNS-blocked address also looks like this.",
    ),
    Diagnosis.MIXED: (
        "The addresses failed for different reasons.",
        "See each address's own result above — there is no single cause here.",
    ),
}
