/* Runs in docs/model/device/index.html before the app, and joins the app to the 3D model page around it
   (the parent window) with postMessage:
   - a WebSocket whose URL starts with "sim:" is the case's panel: what the app sends on it goes to the page as
     {kind: 'app', msg}, and the page's {kind: 'panel', msg} arrive on it as panel messages;
   - the page cannot use a real camera or microphone, so the camera shows sample photos and the microphone a
     quiet tune;
   - the mock printer's window event goes to the page as {kind: 'printed', detail};
   - the page can ask for a tap at a point of the screen ({kind: 'tap', x, y}) and to resume audio ({kind: 'resume'}).
   Every message carries fretcaseSim: 1. Opened on its own (no page around it), the app runs without a panel. */
(function () {
  'use strict';
  var host = window.parent && window.parent !== window ? window.parent : null;
  function post(m) {
    if (!host) return;
    m.fretcaseSim = 1;
    try { host.postMessage(m, '*'); } catch (e) { /* the page went away */ }
  }

  // ---- the panel socket ----
  var current = null;
  function SimSocket(url) {
    var self = this;
    this.url = url; this.readyState = 0; this.protocol = ''; this.extensions = ''; this.bufferedAmount = 0; this.binaryType = 'blob';
    this.onopen = this.onmessage = this.onclose = this.onerror = null;
    setTimeout(function () {
      if (!host) { self.readyState = 3; if (self.onclose) self.onclose({ code: 1006, reason: 'no panel' }); return; }
      self.readyState = 1;
      current = self;
      if (self.onopen) self.onopen({});
      post({ kind: 'open' });
    }, 0);
  }
  SimSocket.CONNECTING = 0; SimSocket.OPEN = 1; SimSocket.CLOSING = 2; SimSocket.CLOSED = 3;
  SimSocket.prototype.send = function (data) {
    if (this.readyState !== 1) return;
    var msg;
    try { msg = JSON.parse(data); } catch (e) { return; }
    post({ kind: 'app', msg: msg });
  };
  SimSocket.prototype.close = function () {
    if (this.readyState === 3) return;
    var self = this;
    this.readyState = 3;
    if (current === this) { current = null; post({ kind: 'close' }); }
    setTimeout(function () { if (self.onclose) self.onclose({ code: 1000, reason: '' }); }, 0);
  };
  SimSocket.prototype.addEventListener = function () {};
  SimSocket.prototype.removeEventListener = function () {};
  var RealWS = window.WebSocket;
  if (RealWS) {
    var PatchedWS = function (url, protocols) {
      if (String(url).indexOf('sim:') === 0) return new SimSocket(url);
      return protocols === undefined ? new RealWS(url) : new RealWS(url, protocols);
    };
    PatchedWS.CONNECTING = 0; PatchedWS.OPEN = 1; PatchedWS.CLOSING = 2; PatchedWS.CLOSED = 3;
    PatchedWS.prototype = RealWS.prototype;
    window.WebSocket = PatchedWS;
  }

  // ---- audio contexts: kept so that the page can resume them after a press on the 3D case ----
  var contexts = [];
  var RealAC = window.AudioContext || window.webkitAudioContext;
  if (RealAC) {
    var TrackedAC = function (opts) {
      var ctx = opts === undefined ? new RealAC() : new RealAC(opts);
      contexts.push(ctx);
      return ctx;
    };
    TrackedAC.prototype = RealAC.prototype;
    window.AudioContext = TrackedAC;
    if (window.webkitAudioContext) window.webkitAudioContext = TrackedAC;
  }
  function resumeAudio() {
    contexts.forEach(function (c) {
      if (c.state === 'suspended' && c.resume) { try { c.resume().catch(function () {}); } catch (e) { /* not allowed yet */ } }
    });
  }

  // ---- camera and microphone ----
  var photos = ['photos/1.jpg', 'photos/2.jpg', 'photos/3.jpg'].map(function (src) { var im = new Image(); im.src = src; return im; });
  function cameraTracks() {
    var cv = document.createElement('canvas');
    cv.width = 1600; cv.height = 1200;
    var c = cv.getContext('2d'), t0 = performance.now();
    var stream = cv.captureStream(30);
    function draw() {
      // a new sample every 4 s, with a slow drift and zoom like a hand-held camera
      var t = (performance.now() - t0) / 1000, im = photos[Math.floor(t / 4) % photos.length], f = (t % 4) / 4;
      c.fillStyle = '#16120e'; c.fillRect(0, 0, cv.width, cv.height);
      if (im.complete && im.naturalWidth) {
        var s = Math.max(cv.width / im.naturalWidth, cv.height / im.naturalHeight) * (1.05 + 0.05 * f);
        var w = im.naturalWidth * s, h = im.naturalHeight * s;
        c.drawImage(im, (cv.width - w) / 2 + Math.sin(t * 0.7) * 14, (cv.height - h) / 2 + Math.cos(t * 0.5) * 9, w, h);
      }
      if (stream.active) setTimeout(draw, 33);
    }
    draw();
    return stream.getVideoTracks();
  }
  function micTracks() {
    var ctx = new RealAC();
    var osc = ctx.createOscillator(), gain = ctx.createGain(), dest = ctx.createMediaStreamDestination();
    var notes = [220, 247, 262, 294, 330, 294, 262, 247], k = 0;
    gain.gain.value = 0.05;
    osc.connect(gain); gain.connect(dest); osc.start();
    contexts.push(ctx);
    var timer = setInterval(function () { osc.frequency.setValueAtTime(notes[k++ % notes.length], ctx.currentTime); }, 400);
    var tracks = dest.stream.getAudioTracks();
    tracks.forEach(function (tr) {
      var stop = tr.stop.bind(tr);
      tr.stop = function () { clearInterval(timer); try { osc.stop(); ctx.close(); } catch (e) { /* already closed */ } stop(); };
    });
    return tracks;
  }
  var md = navigator.mediaDevices;
  if (!md) { try { md = {}; Object.defineProperty(navigator, 'mediaDevices', { value: md, configurable: true }); } catch (e) { md = null; } }
  if (md) {
    md.getUserMedia = function (want) {
      return new Promise(function (resolve, reject) {
        try {
          var out = new MediaStream();
          if (want && want.video) cameraTracks().forEach(function (t) { out.addTrack(t); });
          if (want && want.audio && RealAC) micTracks().forEach(function (t) { out.addTrack(t); });
          resolve(out);
        } catch (e) { reject(e); }
      });
    };
  }

  // ---- a tap from the page (touch screens, where the first touch lands on the 3D picture) ----
  function tap(x, y) {
    var el = document.elementFromPoint(x, y);
    if (!el) return;
    var o = { bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y, view: window, button: 0, pointerId: 1, pointerType: 'touch', isPrimary: true };
    var P = window.PointerEvent || window.MouseEvent;
    el.dispatchEvent(new P('pointerdown', o));
    el.dispatchEvent(new MouseEvent('mousedown', o));
    if (el.focus) { try { el.focus(); } catch (e) { /* not focusable */ } }
    el.dispatchEvent(new P('pointerup', o));
    el.dispatchEvent(new MouseEvent('mouseup', o));
    el.dispatchEvent(new MouseEvent('click', o));
  }

  window.addEventListener('message', function (e) {
    if (!host || e.source !== host) return;
    var d = e.data;
    if (!d || d.fretcaseSim !== 1) return;
    if (d.kind === 'panel' && current && current.readyState === 1 && current.onmessage) current.onmessage({ data: JSON.stringify(d.msg) });
    else if (d.kind === 'resume') resumeAudio();
    else if (d.kind === 'tap') tap(+d.x, +d.y);
  });

  // ---- the mock printer ----
  window.addEventListener('fretcase:mock-print', function (e) { post({ kind: 'printed', detail: e.detail }); });
  window.addEventListener('load', function () { post({ kind: 'ready' }); });
})();
