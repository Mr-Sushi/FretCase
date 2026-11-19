'use strict';
// Prints every message a scripted session sends, as a JSON array, for the schema test.
const PanelClient = require('../panel-client.js');
const FakeWebSocket = require('./fake-ws.js');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const c = new PanelClient({ WebSocketImpl: FakeWebSocket, flushMs: 5, pingMs: 20, timeoutMs: 1000 });
  c.start('ws://x/ws/panel');
  const ws = FakeWebSocket.instances[0];
  ws.open();
  c.key('capture', 'down');
  await sleep(10);
  c.key('capture', 'up');
  c.platter(3); c.platter(-1);
  c.knob('brightness', 2); c.knob('tempo', -40); // split at 32
  c.fader('vocal', 0.1); c.fader('guitar', 1); c.fader('drums', 0);
  for (const id of ['play', 'undo', 'another', 'track.vocal', 'track.melody', 'track.guitar', 'track.bass', 'track.drums', 'track.ambience']) {
    c.key(id, 'down');
  }
  await sleep(40);
  ws.receive({ v: 1, type: 'ping', seq: 1, t: 1 });
  ws.receive({ v: 1, type: 'peer.status', seq: 0, t: 1, payload: { panel: true, app: false } });
  ws.receive({ v: 1, type: 'peer.status', seq: 1, t: 1, payload: { panel: true, app: true } });
  await sleep(30);
  c.stop();
  console.log(JSON.stringify(ws.sent));
})();
