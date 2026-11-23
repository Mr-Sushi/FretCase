# device/simulator

On-screen 2D panel. Connects to `/ws/panel` as the panel and sends the same messages as the hardware; shows the lights the app sends. Stands in for the controller until the hardware arrives. Owner: agent C.

A static page: no build step, no dependencies, no network needed.

| File | What |
| --- | --- |
| `index.html`, `style.css` | Page and styling (labels in Simplified Chinese) |
| `sim.js` | Draws the panel in SVG, turns pointer and keyboard input into calls on the client, draws the lights |
| `panel-client.js` | The panel side of the protocol, without any DOM (also runs in Node): hello and snapshot, summed platter and knob detents, filtered faders, key down and up, ping, reconnect |
| `tests/` | Node tests, a fake WebSocket, and a script whose output `test_simulator.py` validates against the panel schema |

## Run

Either open `index.html` directly in a browser, or serve the folder:

```
python3 -m http.server 8080 --directory device/simulator
# then open http://localhost:8080/
```

With no server address the panel runs offline: every message it would send is built, numbered and shown in the log (marked with a dot) but not sent. Enter an address in the box and press Connect, or open the page with the address in the URL:

```
http://localhost:8080/?ws=wss://<pi>:8443/ws/panel
```

A page served over https can only open `wss://` addresses (browsers block `ws://` from https pages); a page opened from a file or from plain http may use either. For `wss://` with a local certificate, the browser must trust it (open the server's address once and accept it, or install the mkcert root).

The last address used is remembered but not connected automatically; use `?ws=` for that.

The Screen menu (Capture, Pick, Shape, Tracks, Lyrics, Card) puts the screen name in front of every log line, to make it easy to follow which screen a test run was on. It is a local label only: the panel protocol is unchanged and nothing about the screen is sent.

## Controls

| Control | Input | Message |
| --- | --- | --- |
| Platter | Drag around the centre, or scroll the wheel over it (24 detents per turn; clockwise is positive) | `platter.turn` |
| Knobs Bright, Complex, Density, Tempo | Drag up or down (up is clockwise), or scroll the wheel | `knob.turn` |
| Faders | Drag the handle or click the slot | `fader.move` |
| Round keys Capture, Play, Undo, Another | Press and hold with the pointer; keys C, P, U, A | `key` down and up |
| Track keys | Press and hold; keys 1 to 6 | `key` down and up |

Lights: `ring.set` colours the 16 lights around the platter (clockwise from the top, brightness applied); `key.light` sets off, on, blink or pulse on a key. As on the hardware, the capture key and the track keys keep their own colour and ignore the colour field. The capture key and track keys start lit, the others start dark.

## Tests

```
cd device && uv run pytest simulator       # needs node
node --test simulator/tests/panel-client.test.js
```
