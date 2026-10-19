"""The release workflows build their id and upload to `rolling` one way (D64).

release.yml (.dmg), windows-rolling.yml (.zip) and flatpak-build.yml each had a
hand copy of the build-id derivation — and two read the commit SHA differently
— plus two copies of the wait-then-upload loop. They now call
``scripts/build_id.sh`` and ``scripts/upload_to_rolling.sh``; this fails if a
workflow grows its own copy again.
"""

from pathlib import Path

_WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _text(name: str) -> str:
    return (_WORKFLOWS / name).read_text(encoding="utf-8")


def test_no_workflow_writes_the_build_id_file_itself():
    for wf in sorted(_WORKFLOWS.glob("*.yml")):
        assert "_build_id.py" not in wf.read_text(encoding="utf-8"), (
            f"{wf.name} writes metatv/_build_id.py itself — call scripts/build_id.sh --stamp")


def test_every_packaging_workflow_stamps_through_the_script():
    for name in ("release.yml", "windows-rolling.yml", "flatpak-build.yml"):
        assert "scripts/build_id.sh --stamp" in _text(name), name


def test_only_release_yml_uploads_to_rolling_directly():
    """release.yml owns the release (creates and moves it); the others add an
    asset and must wait for it, which is what the script does."""
    for wf in sorted(_WORKFLOWS.glob("*.yml")):
        if wf.name == "release.yml":
            continue
        assert "gh release upload" not in wf.read_text(encoding="utf-8"), (
            f"{wf.name} uploads by hand — call scripts/upload_to_rolling.sh")
