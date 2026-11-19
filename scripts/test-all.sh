#!/usr/bin/env sh
# Run every test suite in the repository, one after another.
# engine/tests and server/tests each have a conftest.py imported as "conftest",
# so they run as separate pytest sessions.
set -e
cd "$(dirname "$0")/.."

echo "== shared schemas"
uv run --with jsonschema --with pytest --with rfc3339-validator pytest -q shared/schema/tests
echo "== engine (ported FretStudio tests)"
uv run pytest -q engine/tests/ported
echo "== engine"
uv run pytest -q engine/tests --ignore=engine/tests/ported
echo "== server"
uv run pytest -q server/tests
echo "== device"
(cd device && uv run pytest -q)
echo "== app"
(cd app && npm run gen --silent && npx tsc --noEmit && npm test --silent)
