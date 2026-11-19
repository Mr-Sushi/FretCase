# server

FastAPI backend that runs on the Raspberry Pi: song sessions, history (undo, another take), locks, generation endpoints, rendering adapters, hum transcription, card endpoints (calling device/card), location, panel relay. Owner: agent A.

## Run and test

```
uv sync --extra hum          # Basic Pitch runs on its bundled ONNX model (no tensorflow)
FRETCASE_DATA=./data uv run uvicorn fretcase_server.main:app --port 8000
uv run pytest server/tests
```

Settings come from the environment: `FRETCASE_DATA`, `FRETCASE_SHARE_BASE`, `FRETCASE_PRINTER` (unset: the printer writes PNG files under the data directory), `FRETCASE_HTTP_TIMEOUT`, `FRETCASE_APP_DIST` (the built app, default `app/dist`; serves `/s/{shareId}` and the song page's files), and for lyrics `FRETCASE_TEXT_MODEL_URL`, `FRETCASE_TEXT_MODEL_KEY`, `FRETCASE_TEXT_MODEL_NAME` (Anthropic Messages API format; without them the lyrics endpoints answer 503). `FRETCASE_SHARE_BASE` defaults to the server's own origin. `FRETCASE_PRINTER` is `dry_run`, `instax[:<address>]` or `thermal:usb:<vid>:<pid>`. Outside services are reached only through `fretcase_server/adapters.py`; the only one used in milestone 2 is the text model for lyrics. The card module `fretcase_card` is imported lazily; tests use the stub in `server/tests/stubs/`.
