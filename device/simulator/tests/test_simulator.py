"""Runs the simulator's JavaScript tests and checks its messages against the panel schema."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fretcase_bridge.schema import errors_for

HERE = Path(__file__).parent
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def test_node_unit_tests():
    r = subprocess.run(
        [NODE, "--test", str(HERE / "panel-client.test.js")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_every_message_the_simulator_sends_is_valid():
    r = subprocess.run([NODE, str(HERE / "emit-messages.js")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    messages = json.loads(r.stdout)
    types = {m["type"] for m in messages}
    assert {"hello", "snapshot", "key", "platter.turn", "knob.turn", "fader.move", "ping", "pong"} <= types
    for m in messages:
        assert errors_for(m) == [], m
    # seq counts up from 0 without gaps on one connection
    assert [m["seq"] for m in messages] == list(range(len(messages)))
    # splits respect the schema limits (-32..32 for knobs)
    tempo = [m["payload"]["delta"] for m in messages if m["type"] == "knob.turn" and m["payload"]["knob"] == "tempo"]
    assert sum(tempo) == -40 and all(abs(d) <= 32 for d in tempo)
