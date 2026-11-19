'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const PanelClient = require('../panel-client.js');
const FakeWebSocket = require('./fake-ws.js');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function make(extra) {
  FakeWebSocket.reset();
  const log = [];
  const lights = { ring: null, keys: [] };
  const status = [];
  const client = new PanelClient(Object.assign({
    WebSocketImpl: FakeWebSocket,
    flushMs: 5, pingMs: 30, timeoutMs: 100, backoff: [10, 20],
    onLog: (e) => log.push(e),
    onRing: (p, b) => { lights.ring = { p, b }; },
    onKeyLight: (id, mode, color) => lights.keys.push({ id, mode, color }),
    onStatus: (s) => status.push(s),
  }, extra));
  return { client, log, lights, status };
}
const outs = (log, type) => log.filter((e) => e.dir === 'out' && e.msg.type === type);

test('offline: hello and snapshot are logged but not sent, seq counts up', () => {
  const { client, log } = make();
  client.start(null);
  client.key('capture', 'down');
  client.key('capture', 'up');
  assert.deepEqual(log.map((e) => [e.msg.type, e.msg.seq, e.sent]), [
    ['hello', 0, false], ['snapshot', 1, false], ['key', 2, false], ['key', 3, false],
  ]);
  assert.equal(FakeWebSocket.instances.length, 0);
  assert.equal(log[0].msg.payload.role, 'panel');
});

test('connected: hello, snapshot, then events on the wire', async () => {
  const { client, log, status } = make();
  client.start('ws://x/ws/panel');
  const ws = FakeWebSocket.instances[0];
  assert.equal(status.at(-1).link, 'connecting');
  ws.open();
  assert.equal(status.at(-1).link, 'connected');
  client.key('track.guitar', 'down');
  assert.deepEqual(ws.sent.map((m) => [m.type, m.seq]), [['hello', 0], ['snapshot', 1], ['key', 2]]);
  assert.deepEqual(ws.sent[1].payload.keysDown, []);
  assert.equal(ws.sent[2].payload.id, 'track.guitar');
  assert.ok(log.every((e) => e.sent));
  client.stop();
});

test('platter and knob detents are summed per tick, faders filtered', async () => {
  const { client } = make();
  client.start('ws://x');
  const ws = FakeWebSocket.instances[0];
  ws.open();
  ws.sent.length = 0;
  client.platter(1); client.platter(1); client.platter(2);
  client.knob('density', 1); client.knob('density', -3); client.knob('tempo', 2);
  client.fader('drums', 0.5); client.fader('drums', 0.45);
  client.fader('bass', 0.795); // within 0.01 of the snapshot value 0.8: not sent
  await sleep(30);
  const by = (t) => ws.sent.filter((m) => m.type === t);
  assert.deepEqual(by('platter.turn').map((m) => m.payload.delta), [4]);
  assert.deepEqual(by('knob.turn').map((m) => [m.payload.knob, m.payload.delta]), [['density', -2], ['tempo', 2]]);
  assert.deepEqual(by('fader.move').map((m) => [m.payload.track, m.payload.value]), [['drums', 0.45]]);
  client.fader('bass', 0); // the bottom always goes out
  await sleep(20);
  assert.equal(by('fader.move').at(-1).payload.value, 0);
  client.stop();
});

test('back and forth that cancels sends nothing; big deltas are split', async () => {
  const { client } = make();
  client.start('ws://x');
  const ws = FakeWebSocket.instances[0];
  ws.open();
  ws.sent.length = 0;
  client.platter(3); client.platter(-3);
  client.platter(100);
  await sleep(40);
  const d = ws.sent.filter((m) => m.type === 'platter.turn').map((m) => m.payload.delta);
  assert.deepEqual(d, [64, 36]);
  client.stop();
});

test('key repeats are ignored; unknown names throw', () => {
  const { client, log } = make();
  client.start(null);
  client.key('play', 'down'); client.key('play', 'down'); client.key('undo', 'up');
  assert.equal(outs(log, 'key').length, 1);
  assert.throws(() => client.key('scale.1', 'down'));
  assert.throws(() => client.knob('volume', 1));
  assert.throws(() => client.fader('piano', 1));
});

test('lights from the app', () => {
  const { client, lights } = make();
  client.start('ws://x');
  const ws = FakeWebSocket.instances[0];
  ws.open();
  const pixels = ['#e08a12'].concat(new Array(15).fill(null));
  ws.receive({ v: 1, type: 'ring.set', seq: 0, t: 1, payload: { pixels, brightness: 0.5 } });
  assert.deepEqual(lights.ring, { p: pixels, b: 0.5 });
  ws.receive({ v: 1, type: 'ring.set', seq: 1, t: 1, payload: { pixels: ['#fff'] } });
  assert.equal(lights.ring.p.length, 16, 'invalid ring ignored');
  ws.receive({ v: 1, type: 'ring.set', seq: 1, t: 1, payload: { pixels } });
  assert.equal(lights.ring.b, 0.6);
  ws.receive({ v: 1, type: 'key.light', seq: 2, t: 1, payload: { id: 'capture', mode: 'blink' } });
  ws.receive({ v: 1, type: 'key.light', seq: 3, t: 1, payload: { id: 'play', mode: 'on', color: '#ffffff' } });
  ws.receive({ v: 1, type: 'key.light', seq: 4, t: 1, payload: { id: 'nope', mode: 'on' } });
  ws.receive({ v: 1, type: 'key.light', seq: 5, t: 1, payload: { id: 'play', mode: 'glow' } });
  ws.receive('not json');
  assert.deepEqual(lights.keys, [
    { id: 'capture', mode: 'blink', color: null },
    { id: 'play', mode: 'on', color: '#ffffff' },
  ]);
  client.stop();
});

test('answers ping with pong, sends its own pings', async () => {
  const { client } = make({ timeoutMs: 1000 });
  client.start('ws://x');
  const ws = FakeWebSocket.instances[0];
  ws.open();
  ws.receive({ v: 1, type: 'ping', seq: 3, t: 3 });
  assert.equal(ws.sent.at(-1).type, 'pong');
  assert.ok(!('payload' in ws.sent.at(-1)));
  ws.receive({ v: 1, type: 'pong', seq: 0, t: 0 });
  await sleep(80);
  assert.ok(ws.sent.some((m) => m.type === 'ping'));
  client.stop();
});

test('snapshot when the app arrives', () => {
  const { client, status } = make();
  client.start('ws://x');
  const ws = FakeWebSocket.instances[0];
  ws.open();
  client.fader('melody', 0.2);
  const n = () => ws.sent.filter((m) => m.type === 'snapshot').length;
  ws.receive({ v: 1, type: 'peer.status', seq: 0, t: 1, payload: { panel: true, app: true } });
  assert.equal(n(), 1);
  assert.equal(status.at(-1).app, true);
  ws.receive({ v: 1, type: 'peer.status', seq: 1, t: 1, payload: { panel: true, app: false } });
  ws.receive({ v: 1, type: 'peer.status', seq: 2, t: 1, payload: { panel: true, app: true } });
  assert.equal(n(), 2);
  assert.equal(ws.sent.filter((m) => m.type === 'snapshot').at(-1).payload.faders.melody, 0.2);
  client.stop();
});

test('reconnects after the link drops, with a fresh seq', async () => {
  const { client, status } = make();
  client.start('ws://x');
  FakeWebSocket.instances[0].open();
  FakeWebSocket.instances[0].drop();
  assert.equal(status.at(-1).link, 'connecting');
  await sleep(40);
  assert.equal(FakeWebSocket.instances.length, 2);
  FakeWebSocket.instances[1].open();
  assert.deepEqual(FakeWebSocket.instances[1].sent.map((m) => [m.type, m.seq]), [['hello', 0], ['snapshot', 1]]);
  client.stop();
});

test('keeps retrying while the server is down', async () => {
  const { client } = make();
  client.start('ws://x');
  FakeWebSocket.instances[0].drop();
  await sleep(15);
  FakeWebSocket.instances[1].drop();
  await sleep(40);
  assert.ok(FakeWebSocket.instances.length >= 3);
  client.stop();
  const n = FakeWebSocket.instances.length;
  await sleep(50);
  assert.equal(FakeWebSocket.instances.length, n, 'no retries after stop');
});

test('a silent server is treated as down', async () => {
  const { client } = make();
  client.start('ws://x');
  FakeWebSocket.instances[0].open();
  await sleep(300);
  assert.ok(FakeWebSocket.instances.length >= 2);
  client.stop();
});

test('actions while not connected are logged as not sent', () => {
  const { client, log } = make();
  client.start('ws://x'); // still connecting
  client.key('capture', 'down');
  assert.equal(outs(log, 'key')[0].sent, false);
  client.stop();
});
