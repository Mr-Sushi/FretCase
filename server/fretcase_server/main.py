"""Entry point:  uv run uvicorn fretcase_server.main:app --port 8000  (data in $FRETCASE_DATA)."""
from fretcase_server.app import create_app

app = create_app()
