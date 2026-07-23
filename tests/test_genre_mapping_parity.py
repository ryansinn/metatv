"""Doc ↔ code parity for the genre-consolidation mapping (#153).

``docs/GENRE_MAPPING.md`` is the owner-facing, auditable record of how raw
provider genre strings consolidate into canonical genres. This test parses that
document's tables and asserts the live mapping code agrees with every row, so the
doc and ``metatv.core.filter_utils._GENRE_NORM`` can never silently drift:

* Every **Fold map** row ``raw → canonical`` must equal ``normalize_genre(raw)``.
* Every **Kept raw** value must be left unchanged by ``normalize_genre`` (i.e. it
  is *not* remapped — the chart deliberately keeps it as long-tail food for a
  later Tag Janitor pass).

The parser stays simple by design (see ``docs/GENRE_MAPPING.md`` → "Doc ↔ code
parity"): it only reads two clearly-delimited regions — the ``## Fold map`` block
(whose ``Canonical: `X` `` lines name the target and whose table rows carry the
backticked raw values) and the ``## Kept raw`` block. Markdown pipe-escaping
(``\\|``) inside a cell is un-escaped back to a literal ``|``.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

from metatv.core.filter_utils import _GENRE_NORM, normalize_genre

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "GENRE_MAPPING.md"

_CANON_RE = re.compile(r"^Canonical: `(.+)`\s*$")
_ROW_RE = re.compile(r"^\|\s*`(.+?)`")


def _unescape_cell(cell: str) -> str:
    """Recover the literal raw value from a markdown table cell.

    A literal pipe inside a cell is written ``\\|`` in the source table; recover
    it. (Other backslashes are content and are left untouched.)
    """
    return cell.replace("\\|", "|")


def _parse_doc() -> tuple[list[tuple[str, str]], list[str]]:
    """Return ``(folds, keeps)`` parsed from ``docs/GENRE_MAPPING.md``.

    ``folds`` is a list of ``(raw, canonical)`` pairs from the Fold map;
    ``keeps`` is a list of raw values from the Kept-raw section.
    """
    folds: list[tuple[str, str]] = []
    keeps: list[str] = []
    region: str | None = None
    canonical: str | None = None

    for line in DOC_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("## Fold map"):
            region, canonical = "fold", None
            continue
        if line.startswith("## Kept raw"):
            region, canonical = "keep", None
            continue
        # Any other top-level (##, exactly two hashes + space) header ends a
        # parseable region. `### ` subsection headers do NOT (they start "###").
        if line.startswith("## "):
            region, canonical = None, None
            continue

        if region == "fold":
            m = _CANON_RE.match(line)
            if m:
                canonical = m.group(1)
                continue
            r = _ROW_RE.match(line)
            if r and canonical is not None:
                folds.append((_unescape_cell(r.group(1)), canonical))
        elif region == "keep":
            r = _ROW_RE.match(line)
            if r:
                keeps.append(_unescape_cell(r.group(1)))

    return folds, keeps


_FOLDS, _KEEPS = _parse_doc()


# ---------------------------------------------------------------------------
# Parser sanity — if these fail, the doc structure changed and the parser (not
# the mapping) needs attention.
# ---------------------------------------------------------------------------

def test_parser_found_the_fold_map():
    """The Fold map must yield the full charted set (129 chart rows + amendments)."""
    assert len(_FOLDS) >= 130, (
        f"parsed only {len(_FOLDS)} fold rows from {DOC_PATH.name}; the doc "
        "structure or the parser regexes likely changed"
    )


def test_parser_found_the_keep_list():
    """The Kept-raw section must yield the full long tail (325 values + 3 now-raw)."""
    assert len(_KEEPS) >= 300, (
        f"parsed only {len(_KEEPS)} keep-as-is rows from {DOC_PATH.name}"
    )


# ---------------------------------------------------------------------------
# Parity — every documented fold agrees with the live code.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,canonical", _FOLDS, ids=[f"{r}->{c}" for r, c in _FOLDS])
def test_fold_row_matches_code(raw: str, canonical: str):
    """Each documented ``raw → canonical`` is exactly what ``normalize_genre`` returns."""
    got = normalize_genre(raw)
    assert got == canonical, (
        f"docs/GENRE_MAPPING.md says {raw!r} → {canonical!r}, but "
        f"normalize_genre({raw!r}) returned {got!r}. Doc and _GENRE_NORM have drifted."
    )


# ---------------------------------------------------------------------------
# Parity — every documented keep-as-is value is NOT remapped by the code.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", _KEEPS, ids=[repr(k) for k in _KEEPS])
def test_kept_raw_is_not_remapped(raw: str):
    """A Kept-raw value must pass through ``normalize_genre`` unchanged.

    ``normalize_genre`` only HTML-unescapes then looks the (lowercased) string up
    in ``_GENRE_NORM``; a value that folds would come back as a *different*
    canonical. Asserting the output equals the (HTML-unescaped) input proves the
    doc's deliberate non-mapping is honored by the code.
    """
    unescaped = html.unescape(raw)
    got = normalize_genre(raw)
    assert got == unescaped, (
        f"docs/GENRE_MAPPING.md keeps {raw!r} raw, but normalize_genre remapped "
        f"it to {got!r}. Either the fold was unintended or the doc must move this "
        "row into the Fold map."
    )
    assert unescaped.lower() not in _GENRE_NORM, (
        f"{raw!r} is listed as Kept-raw but its lowercased form is a _GENRE_NORM key"
    )


# ---------------------------------------------------------------------------
# Cross-check — no value is both folded and kept-raw.
# ---------------------------------------------------------------------------

def test_no_value_is_both_folded_and_kept():
    fold_raws = {html.unescape(r).lower() for r, _ in _FOLDS}
    keep_raws = {html.unescape(r).lower() for r in _KEEPS}
    overlap = fold_raws & keep_raws
    assert not overlap, f"values appear in both Fold map and Kept raw: {overlap}"
