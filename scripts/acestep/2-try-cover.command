#!/bin/bash
# FretCase: asks the ACE-Step server on this Mac to sing the demo song over our own arrangement.
# Start 1-install-and-start.command first and leave it running.
cd "$(dirname "$0")"
PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then echo "python3 is missing."; exit 1; fi
exec "$PY" try_cover.py "$@"
