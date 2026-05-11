#!/usr/bin/env bash
# Launch script for MetaTV

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Activate virtual environment
source "$SCRIPT_DIR/venv/bin/activate"

# Run MetaTV
python -m metatv "$@"
