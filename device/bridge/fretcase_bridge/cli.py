"""Command line entry point: ``fretcase-bridge`` or ``python -m fretcase_bridge``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import ssl

from .bridge import Bridge
from .mapping import Mapping
from .midi import DEFAULT_PORT_HINTS, MidoPort

DEFAULT_URL = "wss://localhost:8443/ws/panel"


def build_ssl(url: str, cafile: str | None, insecure: bool) -> ssl.SSLContext | None:
    if not url.startswith("wss://"):
        return None
    ctx = ssl.create_default_context(cafile=cafile)
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="fretcase-bridge", description=__doc__)
    p.add_argument("--url", default=os.environ.get("FRETCASE_PANEL_URL", DEFAULT_URL))
    p.add_argument(
        "--midi-port",
        action="append",
        help="part of the controller's MIDI port name; repeat to give several "
        f"(default: {', '.join(DEFAULT_PORT_HINTS)})",
    )
    p.add_argument("--mapping", help="mapping file (default: the built-in mapping)")
    p.add_argument("--cafile", help="CA certificate for the local server (e.g. the mkcert root)")
    p.add_argument("--insecure", action="store_true", help="do not verify the server certificate")
    p.add_argument("--list-ports", action="store_true", help="print MIDI ports and exit")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.list_ports:
        import mido

        print("inputs:", mido.get_input_names())
        print("outputs:", mido.get_output_names())
        return
    midi = MidoPort(tuple(args.midi_port) if args.midi_port else DEFAULT_PORT_HINTS)
    bridge = Bridge(
        args.url,
        midi,
        Mapping.load(args.mapping),
        ssl=build_ssl(args.url, args.cafile, args.insecure),
    )
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        pass
