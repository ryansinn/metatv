"""The one ``QProgressBar`` sheet, and the builder for its two variants.

Seven bars, and five of them composed their own ``QProgressBar::chunk`` rule.
They disagreed on everything a bar has: the trough (``COLOR_LINE``, a 10%
overlay, a 60% black wash), the border (1px, none), the corner radius, and the
height — 6px set with ``setFixedHeight``, 4px scaled by the card zoom, and four
that took whatever Qt's default was. None of that was a decision.

Exactly one difference carries meaning, and it is the CHUNK colour: it says
*what* is progressing — blue for work in flight, orange for a resume position,
the subscription hue for time left on an account. So that is the argument, and
everything else belongs to the sheet.

Same arrangement as ``chip_roles.py`` and ``detail_roles.py``: a role group is
a pure function of the tokens, so it composes here and ``theme`` merges it into
its own globals at import and on every palette switch. ``theme.py`` is on a
shrink-only ratchet and does not need to hold every stylesheet in the app to
own the tokens they are built from.

Unlike those two, ``build()`` returns a callable alongside its string. The
callable closes over the palette snapshot it was built with, exactly as the
strings do, so ``theme.progress_bar`` after a switch is a builder bound to the
NEW palette — and ``theme.style_fn(bar, lambda: theme.progress_bar(...))``
re-reads it on every re-style.
"""

from __future__ import annotations

from typing import Callable, Mapping


def build(t: Mapping[str, object]) -> dict[str, str | Callable[..., str]]:
    """Compose the progress-bar role and its builder from the bound tokens."""
    def _(name: str) -> str:
        return str(t[name])

    border = _("COLOR_BORDER")
    line = _("COLOR_LINE")
    text_hi = _("COLOR_TEXT_HI")
    accent_blue = _("COLOR_ACCENT_BLUE")
    font_sm = _("FONT_SM")
    radius_sm = _("RADIUS_SM")
    radius_none = _("RADIUS_NONE")
    progress_h = _("PROGRESS_H")
    progress_h_thin = _("PROGRESS_H_THIN")

    base = (
        f"QProgressBar {{ border: 1px solid {border}; border-radius: {radius_sm};"
        f" background: {line}; text-align: center; color: {text_hi};"
        f" font-size: {font_sm}; max-height: {progress_h}; }}"
        f"QProgressBar::chunk {{ background: {accent_blue};"
        f" border-radius: {radius_sm}; }}"
    )

    def progress_bar(chunk_color: str | None = None, *, thin: bool = False) -> str:
        """``PROGRESS_BAR`` with the chunk recoloured, at one of two heights.

        Args:
            chunk_color: The filled part, already resolved — a token, or a
                runtime colour such as ``subscription_color()``'s. ``None``
                keeps the role's blue.
            thin: The overlay form: a bar drawn ON something (a poster's watch
                progress) rather than sitting in a form. Borderless, square,
                and ``PROGRESS_H_THIN`` tall, so it stays a hairline instead of
                becoming the thing you look at.

        Returns:
            A stylesheet for
            ``theme.style_fn(bar, lambda: theme.progress_bar(...))``.
        """
        sheet = base
        if chunk_color:
            # The SELECTOR is part of the needle: the trough sets a
            # ``background:`` too, so a bare colour swap would recolour
            # whichever of the two came first in the string.
            sheet = sheet.replace(
                f"QProgressBar::chunk {{ background: {accent_blue}",
                f"QProgressBar::chunk {{ background: {chunk_color}")
        if thin:
            # Appended, not woven in: later rules of equal specificity win, so
            # the overlay form is stated as the difference from the base rather
            # than as a second copy of it.
            sheet += (
                f"QProgressBar {{ border: none; max-height: {progress_h_thin};"
                f" border-radius: {radius_none}; }}"
                f"QProgressBar::chunk {{ border-radius: {radius_none}; }}"
            )
        return sheet

    return {"PROGRESS_BAR": base, "progress_bar": progress_bar}
