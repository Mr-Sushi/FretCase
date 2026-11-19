# shared/schema

Single source of truth for the song model, panel events and API payloads. Owner: lead agent.

| File | What |
| --- | --- |
| `song.schema.json` | The song, as the server stores and returns it |
| `panel-events.schema.json` | Messages on `/ws/panel` between the panel and the app |
| `examples/` | Example songs and messages; `*-invalid.json` must be rejected |
| `tests/test_schemas.py` | Schema validity, examples, and consistency rules the schema cannot express |

The HTTP API is in `../../docs/api.md`. Rhythm presets are in `../data/rhythm-presets.json`.

Run the tests from the repository root:

```
uv run --with jsonschema --with pytest --with rfc3339-validator pytest shared/schema/tests
```

To change an interface: edit the schema, update the examples, make the tests pass, then tell the other agents what changed.
