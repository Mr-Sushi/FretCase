"""Panel WebSocket relay: ``/ws/panel`` (docs/api.md, shared/schema/panel-events.schema.json).

One panel and one app may be connected. The server validates every message against the schema, answers ping
itself, sends ``peer.status`` on every connect and disconnect, and forwards the rest to the other side.
Ping and pong are not forwarded: they test the link to the server, so a missing peer is not mistaken for a dead link.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "shared" / "schema" / "panel-events.schema.json"

# which message types each role may send
FROM_PANEL = {"hello", "snapshot", "platter.turn", "knob.turn", "fader.move", "key", "ping", "pong"}
FROM_APP = {"hello", "ring.set", "key.light", "ping", "pong"}
ALLOWED = {"panel": FROM_PANEL, "app": FROM_APP}
HELLO_TIMEOUT_S = 10.0


class PanelHub:
    def __init__(self, schema_path: Path = SCHEMA_PATH):
        self.validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
        self.sockets: Dict[str, Optional[WebSocket]] = {"panel": None, "app": None}
        self._seq: Dict[int, int] = {}
        self._t0 = time.monotonic()

    @property
    def panel_connected(self) -> bool:
        return self.sockets["panel"] is not None

    def validation_errors(self, message: Any) -> list:
        return [e.message for e in self.validator.iter_errors(message)]

    def _stamp(self, ws: WebSocket, body: Dict[str, Any]) -> Dict[str, Any]:
        seq = self._seq.get(id(ws), 0)
        self._seq[id(ws)] = seq + 1
        return {"v": 1, **body, "seq": seq, "t": int((time.monotonic() - self._t0) * 1000)}

    async def send(self, ws: WebSocket, body: Dict[str, Any]) -> None:
        message = self._stamp(ws, body)
        assert not self.validation_errors(message), message
        try:
            await ws.send_text(json.dumps(message, ensure_ascii=False))
        except Exception:
            pass

    async def error(self, ws: WebSocket, code: str, text: str, seq: Optional[int] = None) -> None:
        payload: Dict[str, Any] = {"code": code, "message": text}
        if isinstance(seq, int) and seq >= 0:
            payload["seq"] = seq
        await self.send(ws, {"type": "error", "payload": payload})

    async def broadcast_status(self) -> None:
        payload = {"panel": self.sockets["panel"] is not None, "app": self.sockets["app"] is not None}
        for ws in [w for w in self.sockets.values() if w is not None]:
            await self.send(ws, {"type": "peer.status", "payload": payload})

    async def handle(self, ws: WebSocket) -> None:
        await ws.accept()
        role: Optional[str] = None
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=HELLO_TIMEOUT_S if role is None else None)
                except asyncio.TimeoutError:
                    await ws.close(code=1008)
                    return
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await self.error(ws, "invalid_message", "Not JSON")
                    continue
                seq = message.get("seq") if isinstance(message, dict) else None
                if isinstance(message, dict) and message.get("v") != 1 and "v" in message:
                    await self.error(ws, "unsupported_version", f"Unsupported protocol version {message.get('v')!r}", seq)
                    continue
                problems = self.validation_errors(message)
                if problems:
                    await self.error(ws, "invalid_message", problems[0][:200], seq)
                    continue
                kind = message["type"]
                if role is None:
                    if kind != "hello":
                        await self.error(ws, "invalid_message", "The first message must be hello", seq)
                        continue
                    wanted = message["payload"]["role"]
                    if self.sockets[wanted] is not None:
                        await self.error(ws, "role_taken", f"Another {wanted} is already connected", seq)
                        await ws.close(code=1008)
                        return
                    role = wanted
                    self.sockets[role] = ws
                    await self.broadcast_status()
                    continue
                if kind not in ALLOWED[role]:
                    await self.error(ws, "invalid_message", f"A {role} may not send {kind}", seq)
                    continue
                if kind == "ping":
                    await self.send(ws, {"type": "pong"})
                    continue
                if kind in ("pong", "hello"):
                    continue
                other = self.sockets["app" if role == "panel" else "panel"]
                if other is not None:
                    try:
                        await other.send_text(raw)
                    except Exception:
                        pass
        except WebSocketDisconnect:
            pass
        finally:
            self._seq.pop(id(ws), None)
            if role is not None and self.sockets.get(role) is ws:
                self.sockets[role] = None
                await self.broadcast_status()
