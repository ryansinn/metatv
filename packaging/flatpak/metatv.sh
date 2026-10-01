#!/bin/sh
# Flatpak entry point: run MetaTV from the source tree installed under
# /app/share/metatv (see io.github.ryansinn.MetaTV.yml).
export PYTHONPATH="/app/share/metatv${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m metatv "$@"
