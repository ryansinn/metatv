"""Where each Config setting is stored: the database profile, config.yaml,
or the QA sidecar — and the YAML codec the file uses.

Split out of ``config.py`` (DETAILS-3 session, 2026-10-09): one concern — the
storage decision for every field — that had grown inside a 2,700-line file
whose real job is declaring the settings themselves.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import yaml
from loguru import logger

#: Filename for the dev-QA sidecar. Its contents are every ``Config`` field
#: whose name starts with ``qa_`` — DERIVED from the prefix, never a list
#: someone maintains, so a tenth qa_ field lands here without anyone
#: remembering this exists.
#:
#: Why it is not in config.yaml: it is 38% of the owner's file (1,797 of 4,768
#: lines) and it is not configuration at all. It is the QA record of how PRs
#: and commits land — the technical companion to What's New — and it grows
#: without bound by design. Keeping it in config.yaml meant every one of the
#: 130 ``config.save()`` call sites rewrote all of it.
QA_STATE_FILENAME = "qa_state.yaml"


def _qa_defaults(model_cls) -> dict:
    """The value each ``qa_`` field has when nobody has touched it.

    Needed because "is there any QA state" is NOT ``any(values)``: two of the
    fields are collapse flags that default to ``True``, so an untouched config
    looks non-empty and every ordinary user would get a sidecar they will
    never use. Comparing against the declared defaults is the precise question.
    """
    out = {}
    for name in _qa_field_names(model_cls):
        field = model_cls.model_fields[name]
        out[name] = (field.default_factory() if field.default_factory is not None
                     else field.default)
    return out


#: Marks a field as PROFILE state — the user's own selections and watermarks,
#: persisted by ``core/profile_store.py`` into the database rather than into
#: ``config.yaml``.
#:
#: Declared ON THE FIELD, not in a list at the bottom of this module, and that
#: is the whole reason it is a marker rather than a tuple of names. This
#: codebase's recurring failure is the enumeration nobody remembers to update —
#: the ``refresh_theme()`` sweep, the hand-listed test config stubs,
#: ``_SETTINGS_APPLIED_HOOKS``. A field that is added without a decision about
#: where it persists gets the default (``config.yaml``), which is the safe
#: answer; a field that IS user state says so where it is declared, next to its
#: docstring, where the person adding it is already looking.
#:
#: Greppable both ways: ``grep json_schema_extra=PROFILE`` lists the profile,
#: and a field's own line tells you where it goes.
PROFILE = {"store": "profile"}


#: The ONLY settings config.yaml keeps: what must be readable before the
#: database is open (where it lives, where data goes, the cold-launch theme,
#: values MainWindow reads before it attaches the store) and the store's own
#: bookkeeping. Everything else — every preference, every remembered UI
#: state, every migration watermark — lives in metatv.db's ``profile`` table.
#: The default is the database; adding a name here is the exception that has
#: to be argued for (owner, 2026-10-09: "config.yaml isn't used. period.").
YAML_ONLY: frozenset[str] = frozenset({
    "config_dir", "data_dir", "cache_dir", "database_url",
    "theme_name",                   # __main__ applies it before MainWindow exists
    "max_stacked_notifications",    # read in MainWindow.__init__ before attach
    "profile_store_populated",      # the profile store's own "have I migrated" flag
})


def _profile_field_names(model_cls) -> "set[str]":
    """Every field stored in the database profile: all of them, except
    :data:`YAML_ONLY`, the ``qa_`` sidecar fields and the legacy ``*_icon``
    constants (static glyphs read before attach; never user state).

    Derived from the model, exactly as ``_qa_field_names`` is derived from the
    ``qa_`` prefix. ``profile_store.attach`` takes this rather than owning a
    list, so the store cannot disagree with the declarations. A field marked
    :data:`PROFILE` is in it like any other; the marker now only documents.
    """
    return {
        name for name in model_cls.model_fields
        if name not in YAML_ONLY and not name.startswith("qa_")
        and not name.endswith("_icon")
    }


def _qa_field_names(model_cls) -> "set[str]":
    """Every ``qa_``-prefixed field name on *model_cls*.

    Derived rather than enumerated, for the reason this codebase keeps
    relearning: a hand-kept list is only right until the next field is added
    by someone who does not know the list exists.
    """
    return {name for name in model_cls.model_fields if name.startswith("qa_")}


#: PyYAML's C emitter when the platform has libyaml, else the pure-Python one.
#:
#: Measured on the owner's 130 KB config: 69.5 ms pure Python, 12.2 ms with
#: libyaml — and ``yaml.dump`` was 69 of the 75 ms a save costs, so this IS the
#: cost of saving. The startup log showed 13 saves in 57 seconds, 1.8 s of
#: blocking work on the UI thread.
#:
#: The two emitters differ only in where they wrap long lines; the parsed
#: result is identical, verified against every key in that config. Falls back
#: silently because libyaml is optional and macOS CI may not have it.
_YamlDumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)

#: Likewise for reading.
_YamlLoader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def icon_field_defaults(model_cls) -> dict:
    """``{name: default}`` for the legacy ``*_icon`` glyph constants — never
    user-set (icons live in ``icons.py``), so config.yaml does not carry them."""
    return {k: f.default for k, f in model_cls.model_fields.items() if k.endswith("_icon")}


def atomic_yaml_write(target: Path, payload: dict) -> None:
    """Write *payload* to *target* via a temp file and an atomic replace.

    One writer for config.yaml and the QA sidecar so they cannot drift on how
    they are written — the temp-then-replace is what stops a crash mid-write
    leaving a truncated file.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=target.parent, delete=False, suffix=".yaml"
        ) as tmp:
            tmp_path = Path(tmp.name)
            yaml.dump(payload, tmp, Dumper=_YamlDumper, default_flow_style=False)
        tmp_path.replace(target)
    except Exception as e:
        logger.error(f"Failed to write {target}: {e}")
        try:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
        except OSError:
            pass  # best-effort cleanup of a temp file we are already abandoning
        raise
