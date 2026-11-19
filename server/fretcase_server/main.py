"""Entry point:  uv run uvicorn fretcase_server.main:app --port 8000  (data in $FRETCASE_DATA).

Settings come from the environment; a gitignored .env file at the repository root (or FRETCASE_ENV_FILE) is read
first, so a model key can live there instead of in the shell."""
from fretcase_server.config import load_env_file

load_env_file()

from fretcase_server.app import create_app  # noqa: E402 (the environment must be loaded first)

app = create_app()
