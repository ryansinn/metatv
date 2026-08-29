"""A chip's tooltip must add information, not repeat the chip.

Owner report: hovering a language chip showed "Language: " followed by the
same abbreviation already visible on the chip — "so worthless".

Two things were wrong, and the tests here pin both:

* a named code has to resolve to its NAME ("Language: Arabic (AR)"), which is
  the entire reason a tooltip exists on a two-letter chip;
* an UNNAMED code must not be labelled a language at all. The old fallback
  emitted "Language: XX", which repeated the chip and asserted a fact the app
  does not have — an unmapped token may be a region, a platform, or something
  the provider invented.
"""

import pytest

from metatv.core.channel_name_utils import REGION_FULL_NAMES
from metatv.gui.channel_row_cells import _code_tip


@pytest.mark.parametrize("code,name", [("EN", "English"), ("AR", "Arabic")])
def test_named_code_tooltip_states_the_name(code: str, name: str) -> None:
    """The tooltip expands the abbreviation — the whole point of the hover."""
    assert REGION_FULL_NAMES.get(code) == name, "fixture drifted from the table"
    tip = _code_tip(code, kind="Language", action="click to show only this language")
    assert f"Language: {name} ({code})" in tip


def test_unnamed_code_tooltip_does_not_echo_the_chip() -> None:
    """No 'Language: XX'. Fails on the pre-fix f-string, which emitted exactly that."""
    code = "ZQX"
    assert code not in REGION_FULL_NAMES, "pick a code the table really lacks"
    tip = _code_tip(code, kind="Language", action="click to show only this language")

    assert f"Language: {code}" not in tip, f"tooltip repeats the chip: {tip!r}"
    assert "no known language" in tip, f"tooltip must say the name is unknown: {tip!r}"
    assert code in tip, "the raw code is still worth showing"


def test_unnamed_code_keeps_the_click_hint() -> None:
    """The action half stayed useful even when the name half was not — don't lose it."""
    tip = _code_tip("ZQX", kind="Region", action="click to show only this region")
    assert tip.endswith("click to show only this region")
    assert "no known region" in tip
