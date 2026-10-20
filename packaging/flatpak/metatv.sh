#!/bin/sh
# Flatpak entry point: run MetaTV's compiled module installed under
# /app/share/metatv (see io.github.ryansinn.MetaTV.yml). `-c` rather than
# `-m metatv`: the package is one compiled extension, and its __main__ is
# imported like any submodule.
export PYTHONPATH="/app/share/metatv${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -c "from metatv.__main__ import main; main()" "$@"
