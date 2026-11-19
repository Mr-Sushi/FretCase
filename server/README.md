# server

FastAPI backend that runs on the Raspberry Pi: song sessions, history (undo, another take), locks, generation endpoints, rendering adapters, hum transcription, card endpoints (calling device/card), location, panel relay. Owner: agent A.

## Run and test

```
uv sync --extra hum          # Basic Pitch runs on its bundled ONNX model (no tensorflow)
FRETCASE_DATA=./data uv run uvicorn fretcase_server.main:app --port 8000
uv run pytest server/tests
```

Settings come from the environment: `FRETCASE_DATA`, `FRETCASE_SHARE_BASE`, `FRETCASE_PRINTER` (unset: the printer writes PNG files under the data directory), `FRETCASE_HTTP_TIMEOUT`, `FRETCASE_APP_DIST` (the built app, default `app/dist`; serves `/s/{shareId}` and the song page's files), and for lyrics `FRETCASE_TEXT_MODEL_KEY` (required to turn lyrics on), `FRETCASE_TEXT_MODEL_NAME` (default `claude-sonnet-5-5`) and `FRETCASE_TEXT_MODEL_URL` (default `https://api.anthropic.com`; Anthropic Messages API format). Without a key the lyrics endpoints answer 503 with `reason: not_configured`. `FRETCASE_SHARE_BASE` defaults to the server's own origin. `FRETCASE_PRINTER` is `dry_run`, `instax[:<address>]` or `thermal:usb:<vid>:<pid>`. Outside services are reached only through `fretcase_server/adapters.py`; the only one used in milestone 2 is the text model for lyrics. The card module `fretcase_card` is imported lazily; tests use the stub in `server/tests/stubs/`.

## Lyrics with a model

Put the key in a `.env` file at the repository root (it is gitignored and read at start-up without overriding the environment):

```sh
cp .env.example .env      # then fill in FRETCASE_TEXT_MODEL_KEY
uv run python scripts/try-lyrics.py "海边的傍晚，风很大，有点想家"
```

`scripts/try-lyrics.py` makes a song in a throwaway folder through the real API, asks for lyrics and three other wordings, and prints each line with its length against the notes and how long the calls took.
