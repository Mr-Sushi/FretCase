#!/bin/sh
# Regenerates fretcase_engine/song_model.py from the shared schema.
# Run from the repository root:  sh engine/gen_song_model.sh
uv run datamodel-codegen \
  --input shared/schema/song.schema.json --input-file-type jsonschema \
  --output-model-type pydantic_v2.BaseModel --use-annotated --collapse-root-models \
  --target-python-version 3.11 --use-double-quotes --disable-timestamp --formatters black \
  --output engine/fretcase_engine/song_model.py
