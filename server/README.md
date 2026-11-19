# server

FastAPI backend that runs on the Raspberry Pi: song sessions, history (undo, another take), locks, generation endpoints, rendering adapters, hum transcription, card endpoints (calling device/card), location, panel relay. Owner: agent A.

## Run and test

```
uv sync --extra hum          # Basic Pitch runs on its bundled ONNX model (no tensorflow)
FRETCASE_DATA=./data uv run uvicorn fretcase_server.main:app --port 8000
uv run pytest server/tests
```

Settings come from the environment: `FRETCASE_DATA`, `FRETCASE_SHARE_BASE`, `FRETCASE_PRINTER` (unset: the printer writes PNG files under the data directory), `FRETCASE_HTTP_TIMEOUT`. Outside services are reached only through `fretcase_server/adapters.py`; none is used in milestone 1. The card module `fretcase_card` is imported lazily; tests use the stub in `server/tests/stubs/`.
