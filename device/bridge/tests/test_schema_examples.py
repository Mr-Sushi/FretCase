"""The shared example messages, as a guard that the bridge validates the same way as the schema tests."""
import json

from fretcase_bridge.schema import errors_for, find_schema_path


def test_shared_examples():
    ex = find_schema_path().parent / "examples"
    for m in json.loads((ex / "panel-messages.json").read_text()):
        assert errors_for(m) == [], m
    for case in json.loads((ex / "panel-messages-invalid.json").read_text()):
        assert errors_for(case["msg"]) != [], case["why"]
