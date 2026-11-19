// Panel-side protocol for the FretCase simulator (and anything else that plays the panel).
// Pure logic, no DOM: works in the browser and in Node (for the tests).
//
// It sends exactly what the hardware bridge sends (shared/schema/panel-events.schema.json):
// hello and snapshot after connecting, platter/knob deltas summed over 20 ms, faders filtered to
// steps of 0.01, key down/up at once, ping every 2 s, reconnect with back-off. Without a server
// URL it runs offline: every message is built and logged but not sent.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PanelClient = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var TRACKS = ['vocal', 'melody', 'guitar', 'bass', 'drums', 'ambience'];
  var KNOBS = ['brightness', 'complexity', 'density', 'tempo'];
  var KEYS = ['capture', 'play', 'undo', 'another'].concat(TRACKS.map(function (t) { return 'track.' + t; }));
  var MODES = ['off', 'on', 'blink', 'pulse'];
  var COLOR = /^#[0-9a-fA-F]{6}$/;

  function noop() {}

  function PanelClient(opts) {
    opts = opts || {};
    this.WebSocketImpl = opts.WebSocketImpl || (typeof WebSocket !== 'undefined' ? WebSocket : null);
    this.clock = opts.clock || function () { return Date.now(); };
    this.setTimeout = opts.setTimeout || function (f, ms) { return setTimeout(f, ms); };
    this.clearTimeout = opts.clearTimeout || function (h) { clearTimeout(h); };
    this.name = opts.name || 'simulator';
    this.flushMs = opts.flushMs || 20;
    this.pingMs = opts.pingMs || 2000;
    this.timeoutMs = opts.timeoutMs || 5000;
    this.backoff = opts.backoff || [500, 1000, 2000, 5000];
    this.onLog = opts.onLog || noop;       // ({ dir: 'out'|'in', sent: bool, msg })
    this.onRing = opts.onRing || noop;     // (pixels[16], brightness)
    this.onKeyLight = opts.onKeyLight || noop; // (id, mode, color|null)
    this.onStatus = opts.onStatus || noop; // ({ link: 'offline'|'connecting'|'connected', app: bool|null })

    this.t0 = this.clock();
    this.seq = 0;
    this.url = null;
    this.ws = null;
    this.link = 'offline';
    this.app = null;
    this.faders = {};
    TRACKS.forEach(function (t) { this.faders[t] = 0.8; }, this);
    this.keysDown = {};
    this._sentFader = {};
    this._pPlatter = 0;
    this._pKnobs = {};
    this._pFaders = {};
    this._flushTimer = null;
    this._pingTimer = null;
    this._retryTimer = null;
    this._failures = 0;
    this._lastRx = 0;
    this._appPresent = null;
    this._wantConnection = false;
  }

  PanelClient.TRACKS = TRACKS;
  PanelClient.KNOBS = KNOBS;
  PanelClient.KEYS = KEYS;

  var P = PanelClient.prototype;

  P.now = function () { return Math.max(0, Math.round(this.clock() - this.t0)); };

  P._status = function (link) {
    if (link) this.link = link;
    this.onStatus({ link: this.link, app: this.app });
  };

  // ---- sending ---------------------------------------------------------------------------

  P._build = function (type, payload, t) {
    var msg = { v: 1, type: type, seq: this.seq++, t: t === undefined ? this.now() : t };
    if (payload !== undefined) msg.payload = payload;
    return msg;
  };

  P._send = function (type, payload, t) {
    var msg = this._build(type, payload, t);
    var live = this.ws && this.ws.readyState === 1 && this.link === 'connected';
    if (live) {
      try { this.ws.send(JSON.stringify(msg)); } catch (e) { live = false; }
    }
    this.onLog({ dir: 'out', sent: !!live, msg: msg });
    return msg;
  };

  P.snapshotPayload = function () {
    var faders = {};
    TRACKS.forEach(function (t) { faders[t] = this.faders[t]; }, this);
    return { faders: faders, keysDown: KEYS.filter(function (k) { return this.keysDown[k]; }, this) };
  };

  P._beginSession = function () {
    this.seq = 0;
    this._pPlatter = 0;
    this._pKnobs = {};
    this._pFaders = {};
    this._appPresent = null;
    this._send('hello', { role: 'panel', name: this.name, firmware: 'simulator-0.1.0' });
    this._send('snapshot', this.snapshotPayload());
    this._sentFader = {};
    TRACKS.forEach(function (t) { this._sentFader[t] = this.faders[t]; }, this);
  };

  // ---- controls --------------------------------------------------------------------------

  P._schedule = function () {
    if (this._flushTimer !== null) return;
    var self = this;
    this._flushTimer = this.setTimeout(function () { self._flushTimer = null; self._flush(); }, this.flushMs);
  };

  P._flush = function () {
    var more = false;
    var t = this.now();
    if (this._pPlatter) {
      var step = Math.max(-64, Math.min(64, this._pPlatter));
      this._pPlatter -= step;
      this._send('platter.turn', { delta: step }, t);
      if (this._pPlatter) more = true;
    }
    Object.keys(this._pKnobs).forEach(function (k) {
      var total = this._pKnobs[k];
      var s = Math.max(-32, Math.min(32, total));
      if (total === s) delete this._pKnobs[k]; else { this._pKnobs[k] = total - s; more = true; }
      if (s) this._send('knob.turn', { knob: k, delta: s }, t);
    }, this);
    Object.keys(this._pFaders).forEach(function (tr) {
      var v = this._pFaders[tr];
      var last = this._sentFader[tr];
      var atEnd = (v === 0 || v === 1) && v !== last;
      if (last === undefined || Math.abs(v - last) >= 0.01 - 1e-9 || atEnd) {
        this._sentFader[tr] = v;
        delete this._pFaders[tr];
        this._send('fader.move', { track: tr, value: v }, t);
      }
    }, this);
    if (more) this._schedule();
  };

  P.platter = function (delta) {
    delta = Math.trunc(delta);
    if (!delta) return;
    this._pPlatter += delta;
    this._schedule();
  };

  P.knob = function (knob, delta) {
    if (KNOBS.indexOf(knob) < 0) throw new Error('unknown knob ' + knob);
    delta = Math.trunc(delta);
    if (!delta) return;
    this._pKnobs[knob] = (this._pKnobs[knob] || 0) + delta;
    this._schedule();
  };

  P.fader = function (track, value) {
    if (TRACKS.indexOf(track) < 0) throw new Error('unknown track ' + track);
    value = Math.max(0, Math.min(1, Math.round(value * 1000) / 1000));
    this.faders[track] = value;
    this._pFaders[track] = value;
    this._schedule();
  };

  P.key = function (id, action) {
    if (KEYS.indexOf(id) < 0) throw new Error('unknown key ' + id);
    var down = action === 'down';
    if (!!this.keysDown[id] === down) return;
    if (down) this.keysDown[id] = true; else delete this.keysDown[id];
    this._send('key', { id: id, action: action });
  };

  // ---- connection ------------------------------------------------------------------------

  // Start without a server (log only) or with a URL.
  P.start = function (url) {
    this.stop();
    this.url = url || null;
    if (!this.url) {
      this._wantConnection = false;
      this._status('offline');
      this._beginSession(); // logs hello and snapshot as "would send"
      return;
    }
    this._wantConnection = true;
    this._failures = 0;
    this._open();
  };

  P.stop = function () {
    this._wantConnection = false;
    this._clearTimers();
    if (this.ws) {
      var ws = this.ws;
      this.ws = null;
      ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
      try { ws.close(); } catch (e) { /* already closed */ }
    }
    this.app = null;
    this._status('offline');
  };

  P._clearTimers = function () {
    [this._pingTimer, this._retryTimer].forEach(function (h) { if (h !== null) this.clearTimeout(h); }, this);
    this._pingTimer = this._retryTimer = null;
  };

  P._open = function () {
    var self = this;
    if (!this.WebSocketImpl) { this._status('offline'); return; }
    this._status('connecting');
    var ws;
    try { ws = new this.WebSocketImpl(this.url); } catch (e) { this._lost(); return; }
    this.ws = ws;
    ws.onopen = function () {
      if (self.ws !== ws) return;
      self._failures = 0;
      self._lastRx = self.clock();
      self._status('connected');
      self._beginSession();
      self._armPing();
    };
    ws.onmessage = function (ev) { if (self.ws === ws) self._receive(ev.data); };
    ws.onclose = ws.onerror = function () { if (self.ws === ws) self._lost(); };
  };

  P._lost = function () {
    var ws = this.ws;
    this.ws = null;
    if (ws) { ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null; try { ws.close(); } catch (e) { /* ignore */ } }
    this._clearTimers();
    this.app = null;
    this._status('connecting');
    if (!this._wantConnection) return;
    var self = this;
    var delay = this.backoff[Math.min(this._failures, this.backoff.length - 1)];
    this._failures++;
    this._retryTimer = this.setTimeout(function () { self._retryTimer = null; self._open(); }, delay);
  };

  P._armPing = function () {
    var self = this;
    this._pingTimer = this.setTimeout(function () {
      self._pingTimer = null;
      if (self.clock() - self._lastRx > self.timeoutMs) { self._lost(); return; }
      self._send('ping');
      self._armPing();
    }, this.pingMs);
  };

  // ---- receiving -------------------------------------------------------------------------

  function validRing(p) {
    return p && Array.isArray(p.pixels) && p.pixels.length === 16 &&
      p.pixels.every(function (c) { return c === null || (typeof c === 'string' && COLOR.test(c)); }) &&
      (p.brightness === undefined || (typeof p.brightness === 'number' && p.brightness >= 0 && p.brightness <= 1));
  }

  function validKeyLight(p) {
    return p && KEYS.indexOf(p.id) >= 0 && MODES.indexOf(p.mode) >= 0 &&
      (p.color === undefined || (typeof p.color === 'string' && COLOR.test(p.color)));
  }

  P._receive = function (raw) {
    this._lastRx = this.clock();
    var msg;
    try { msg = JSON.parse(raw); } catch (e) { return; }
    if (!msg || msg.v !== 1 || typeof msg.type !== 'string') return;
    this.onLog({ dir: 'in', sent: true, msg: msg });
    var p = msg.payload;
    switch (msg.type) {
      case 'ping': this._send('pong'); break;
      case 'ring.set':
        if (validRing(p)) this.onRing(p.pixels, p.brightness === undefined ? 0.6 : p.brightness);
        break;
      case 'key.light':
        if (validKeyLight(p)) this.onKeyLight(p.id, p.mode, p.color === undefined ? null : p.color);
        break;
      case 'peer.status':
        if (p && typeof p.app === 'boolean') {
          if (p.app && this._appPresent === false) {
            this._send('snapshot', this.snapshotPayload());
            var self = this;
            TRACKS.forEach(function (t) { self._sentFader[t] = self.faders[t]; });
          }
          this._appPresent = p.app;
          this.app = p.app;
          this._status();
        }
        break;
      default: break; // pong, hello, error: nothing to do
    }
  };

  return PanelClient;
});
