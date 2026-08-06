"""Resolve a DTCG token file into a flat ``{"role.name": "#hex"}`` mapping.

Why this layer exists
---------------------
Every palette used to hand-author ~140 colour values. Measured against the
shipped set, that was not padding — no duplicates, no single-use tokens — but it
was **flat**: each value independently chosen, with no rule connecting them. So
adding a theme meant 140 judgement calls, and no published palette could be
dropped in.

Here a palette authors ~6 scale choices and the roles derive from Radix's fixed
step semantics. Importing Nord or Catppuccin becomes: name the scales.

Format
------
`W3C Design Tokens (DTCG) <https://tresor.dev/design-tokens>`_ — ``$value``,
``$type``, ``$description``, and ``{reference}`` aliases. Two MetaTV-specific
keys sit alongside, both prefixed ``$`` so they stay valid DTCG:

``$scales``
    Maps a semantic scale name to a Radix hue (``"neutral": "slate"``). This is
    the entire authoring surface of a theme.
``$mode``
    ``"dark"`` or ``"light"`` — selects the Radix variant and is what the
    palette-kind guard in the tests asserts against.

A reference resolves as ``{scale.step}`` where *scale* is either a name from
``$scales``, a literal Radix hue, or either of those with an ``A`` suffix for
the alpha variant (``{neutralA.3}``). Steps are Radix's own 1-12.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from metatv.gui.tokens import radix

_REF_RE = re.compile(r"^\{([A-Za-z]+)\.(\d{1,2})\}$")


class TokenResolutionError(ValueError):
    """A reference names a scale or step that does not exist.

    Raised rather than silently substituting a fallback colour: a theme that
    half-loads is worse than one that refuses to, because the failure then shows
    up as an unreadable widget somewhere far from the cause.
    """


def _scale_for(name: str, mode: str) -> tuple[str, ...]:
    """Return the vendored Radix tuple for *name* in *mode*.

    ``name`` is a Radix hue, optionally suffixed ``A`` for the alpha variant.
    """
    alpha = name.endswith("A")
    hue = name[:-1] if alpha else name
    attr = f"{hue}{'_A' if alpha else ''}_{mode}".upper()
    scale = getattr(radix, attr, None)
    if scale is None:
        raise TokenResolutionError(
            f"no vendored Radix scale {attr!r} (hue={hue!r}, mode={mode!r})"
        )
    return scale


def _qt_safe(hexstr: str) -> str:
    """Convert a Radix ``#RRGGBBAA`` alpha step into ``rgba(r, g, b, a)``.

    Qt is the reason this cannot be passed through. An 8-digit hex in a Qt
    stylesheet is read as **#AARRGGBB**, while Radix (and CSS) emit
    **#RRGGBBAA** — so ``#ddeaf814`` would silently paint as a near-opaque
    blue-grey instead of a 8%-alpha scrim. Nothing would error; the wrong colour
    would simply appear, which is the worst kind of bug to inherit from a
    vendored dataset.

    ``rgba()`` is also what the rest of the codebase already parses (the chip
    painter reads the old OVERLAY_* tokens in exactly this form), so no consumer
    needs to learn a new format.
    """
    h = hexstr.lstrip("#")
    if len(h) != 8:
        return hexstr
    r, g, b, a = (int(h[i:i + 2], 16) for i in (0, 2, 4, 6))
    return f"rgba({r},{g},{b},{a / 255:.3f})"


def _resolve_value(value: str, scales: dict[str, str], mode: str) -> str:
    match = _REF_RE.match(value.strip())
    if not match:
        # A literal is allowed but should be rare — it is an escape hatch, and
        # the conformance test reports how many a palette uses so the count
        # stays visible rather than creeping.
        return value
    scale_name, step_txt = match.group(1), int(match.group(2))
    alpha = scale_name.endswith("A")
    base = scale_name[:-1] if alpha else scale_name
    hue = scales.get(base, base)          # semantic name → hue, else literal hue
    return _qt_safe(radix.step(_scale_for(f"{hue}A" if alpha else hue, mode), step_txt))


def load_tokens(path: str | Path) -> dict[str, str]:
    """Load a DTCG palette file and return ``{"group.name": "#hex"}``.

    Group and token names are joined with ``.`` — ``surface.base``,
    ``on-surface.strong``, ``facet.language``. Nothing is lower-cased or
    otherwise mangled, so the JSON is the readable source of truth.
    """
    doc: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    scales: dict[str, str] = doc.get("$scales", {})
    mode: str = doc.get("$mode", "dark")
    if mode not in ("dark", "light"):
        raise TokenResolutionError(f"$mode must be 'dark' or 'light', got {mode!r}")

    flat: dict[str, str] = {}
    for group, body in doc.items():
        if group.startswith("$") or not isinstance(body, dict):
            continue
        for name, token in body.items():
            if name.startswith("$") or not isinstance(token, dict):
                continue
            if "$value" not in token:
                continue
            flat[f"{group}.{name}"] = _resolve_value(token["$value"], scales, mode)
    if not flat:
        raise TokenResolutionError(f"{path} resolved to zero tokens")
    return flat


def palette_mode(path: str | Path) -> str:
    """The palette's ``$mode`` — 'dark' or 'light'."""
    return json.loads(Path(path).read_text(encoding="utf-8")).get("$mode", "dark")


def build_legacy_palette(path: str | Path) -> dict[str, str]:
    """Resolve a DTCG palette into the flat ``COLOR_*``/``OVERLAY_*`` dict.

    Covers both name tables in ``legacy_map``: ``LEGACY_TOKEN_MAP`` (the ~140
    pre-restructure names, which shrink as they are converted) and
    ``ROLE_TOKENS`` (new names, each backed by a semantic role).

    This is the bridge that lets ~1800 lines of role constants and every widget
    keep working untouched while their values come from the scale. Entries
    resolve either through a semantic role (``"on-surface.default"``) or a raw
    scale coordinate (``"{neutral.7}"``) — see ``legacy_map``.

    Raises:
        TokenResolutionError: if any legacy name fails to resolve. Loud on
            purpose: a missing key here is an ``AttributeError`` at import time
            in a widget far away, and a *silently wrong* one is worse — it
            paints, just incorrectly.
    """
    from metatv.gui.tokens.legacy_map import LEGACY_TOKEN_MAP, ROLE_TOKENS

    doc: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    scales: dict[str, str] = doc.get("$scales", {})
    mode: str = doc.get("$mode", "dark")
    roles = load_tokens(path)

    out: dict[str, str] = {}
    unresolved: list[str] = []
    # ROLE_TOKENS resolves by exactly the same rules; the two tables are kept
    # apart only so the legacy one's shrinking count stays meaningful.
    for legacy, ref in {**LEGACY_TOKEN_MAP, **ROLE_TOKENS}.items():
        if ref.startswith("{"):
            try:
                out[legacy] = _resolve_value(ref, scales, mode)
            except TokenResolutionError:
                unresolved.append(f"{legacy} -> {ref}")
        elif ref in roles:
            out[legacy] = roles[ref]
        else:
            unresolved.append(f"{legacy} -> role {ref!r} not in palette")
    if unresolved:
        raise TokenResolutionError(
            f"{len(unresolved)} legacy token(s) did not resolve: {unresolved[:5]}"
        )
    return out
