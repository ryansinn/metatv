"""``scripts/rebaseline_code_health.py`` must not rewrite ``_comment``'s encoding.

The baseline's git merge driver (``scripts/merge_code_health_baseline.py``)
writes JSON with the stdlib default (``ensure_ascii`` on), which escapes the
``_comment`` field's em-dash as ``\\u2014``; this script writes with
``ensure_ascii=False``, which emits the literal byte. Two writers, two
encodings of the identical string — so every rebaseline after a merge flipped
that one line, which happened three times on 2026-09-01 and buried the
line-count changes a rebaseline diff exists to show.

The fix: read the EXISTING baseline's raw ``_comment`` JSON text and splice it
back verbatim instead of re-serializing it, so a rebaseline never itself
changes that field's on-disk encoding.
"""

from __future__ import annotations

from pathlib import Path

from scripts.rebaseline_code_health import _DEFAULT_COMMENT, _write_baseline

_ESCAPED_BASELINE = (
    '{\n'
    '  "_comment": "Debt ratchet baseline \\u2014 see docs.",\n'
    '  "file_lines": {\n'
    '    "metatv/foo.py": 1200\n'
    '  },\n'
    '  "get_session_calls": 3\n'
    '}\n'
)


def test_rebaseline_preserves_an_escaped_comment_byte_for_byte(tmp_path: Path) -> None:
    """A ``\\u2014``-escaped comment (the merge driver's encoding) survives untouched."""
    baseline = tmp_path / "code_health_baseline.json"
    baseline.write_text(_ESCAPED_BASELINE, encoding="utf-8")

    _write_baseline({"metatv/foo.py": 1250}, 4, path=baseline)

    text = baseline.read_text(encoding="utf-8")
    assert '"_comment": "Debt ratchet baseline \\u2014 see docs."' in text, (
        "the escaped _comment field must be copied byte-for-byte, not "
        f"re-encoded:\n{text}"
    )
    assert "—" not in text, (
        "a literal em-dash byte must not be introduced by a rebaseline run"
    )
    # The numbers this run WAS asked to update still moved.
    assert '"metatv/foo.py": 1250' in text
    assert '"get_session_calls": 4' in text


def test_rebaseline_preserves_a_literal_em_dash_comment_byte_for_byte(
    tmp_path: Path,
) -> None:
    """The literal-em-dash encoding (this script's own historical output) also survives."""
    baseline = tmp_path / "code_health_baseline.json"
    literal_text = _ESCAPED_BASELINE.replace("\\u2014", "—")
    baseline.write_text(literal_text, encoding="utf-8")

    _write_baseline({"metatv/foo.py": 1250}, 4, path=baseline)

    text = baseline.read_text(encoding="utf-8")
    assert '"_comment": "Debt ratchet baseline — see docs."' in text
    assert "\\u2014" not in text, (
        "a literal-em-dash comment must not be re-escaped by a rebaseline run"
    )


def test_rebaseline_writes_the_default_comment_for_a_brand_new_baseline(
    tmp_path: Path,
) -> None:
    """No existing file → fall back to the documented default comment text."""
    baseline = tmp_path / "code_health_baseline.json"
    assert not baseline.exists()

    _write_baseline({"metatv/foo.py": 1000}, 0, path=baseline)

    text = baseline.read_text(encoding="utf-8")
    assert _DEFAULT_COMMENT in text


def test_running_rebaseline_twice_in_a_row_produces_no_further_diff(
    tmp_path: Path,
) -> None:
    """Two runs back-to-back must not oscillate the ``_comment`` encoding.

    This is the exact symptom from 2026-09-01: a rebaseline diff carrying a
    noise line on ``_comment`` that hid the real (line-count) changes.
    """
    baseline = tmp_path / "code_health_baseline.json"
    baseline.write_text(_ESCAPED_BASELINE, encoding="utf-8")

    _write_baseline({"metatv/foo.py": 1250}, 4, path=baseline)
    once = baseline.read_text(encoding="utf-8")
    _write_baseline({"metatv/foo.py": 1250}, 4, path=baseline)
    twice = baseline.read_text(encoding="utf-8")

    assert once == twice
