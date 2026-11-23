// On-screen panel: draws the controls, turns pointer input into PanelClient calls, shows lights.
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var TRACKS = [
    { id: 'vocal', label: 'Voice', color: '#e2725b' },
    { id: 'melody', label: 'Melody', color: '#e3a14a' },
    { id: 'guitar', label: 'Guitar', color: '#49b8b3' },
    { id: 'bass', label: 'Bass', color: '#5b8dd6' },
    { id: 'drums', label: 'Drums', color: '#9a7bd1' },
    { id: 'ambience', label: 'Ambience', color: '#7fae6a' }
  ];
  var KNOBS = [
    { id: 'brightness', label: 'Bright' },
    { id: 'complexity', label: 'Complex' },
    { id: 'density', label: 'Density' },
    { id: 'tempo', label: 'Tempo' }
  ];
  var ROUND_KEYS = [
    { id: 'capture', label: 'Capture', color: '#d0332b', glow: '#ff5a4d', fixed: true, hotkey: 'c' },
    { id: 'play', label: 'Play', color: '#f1e6c8', glow: '#ffffff', hotkey: 'p' },
    { id: 'undo', label: 'Undo', color: '#f1e6c8', glow: '#ffffff', hotkey: 'u' },
    { id: 'another', label: 'Another', color: '#f1e6c8', glow: '#ffffff', hotkey: 'a' }
  ];
  var DETENTS_PER_TURN = 24;      // platter: one detent every 15 degrees
  var KNOB_PX_PER_DETENT = 8;     // vertical drag distance for one knob detent
  var RING = { cx: 260, cy: 270, ledR: 150, bodyR: 118 };
  var FADER = { top: 330, bottom: 570, handleH: 44, handleW: 32 };
  var KNOB_R = 40;

  var svg = document.getElementById('panel');
  var client = new PanelClient({
    onLog: function (e) { logLine(e); },
    onStatus: function (st) { showStatus(st); },
    onRing: function (pixels, brightness) { ringPixels = pixels.slice(); ringBrightness = brightness; drawRing(); },
    onKeyLight: function (id, mode, color) { setKeyLight(id, mode, color); }
  });

  function el(name, attrs, parent) {
    var n = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(n);
    return n;
  }
  function text(str, x, y, cls, parent) {
    var t = el('text', { x: x, y: y, class: cls }, parent);
    t.textContent = str;
    return t;
  }
  function svgPoint(ev) {
    var pt = svg.createSVGPoint();
    pt.x = ev.clientX; pt.y = ev.clientY;
    return pt.matrixTransform(svg.getScreenCTM().inverse());
  }

  // ---- background -------------------------------------------------------------------------
  var defs = el('defs', {}, svg);
  var grad = el('linearGradient', { id: 'wood', x1: 0, y1: 0, x2: 1, y2: 1 }, defs);
  el('stop', { offset: 0, 'stop-color': '#5d3a24' }, grad);
  el('stop', { offset: 1, 'stop-color': '#3d2517' }, grad);
  el('rect', { x: 0, y: 0, width: 1180, height: 620, rx: 14, fill: 'url(#wood)' }, svg);
  [[22, 22], [1158, 22], [22, 598], [1158, 598]].forEach(function (p) {
    el('circle', { cx: p[0], cy: p[1], r: 7, fill: '#b8923f', stroke: '#5c4719', 'stroke-width': 2 }, svg);
  });

  // ---- platter and ring -------------------------------------------------------------------
  var ringLeds = [];
  var ringBrightness = 0.6;
  var ringPixels = new Array(16).fill(null);
  for (var i = 0; i < 16; i++) {
    var a = (-90 + i * 22.5) * Math.PI / 180; // clockwise from the top
    ringLeds.push(el('circle', {
      cx: RING.cx + RING.ledR * Math.cos(a), cy: RING.cy + RING.ledR * Math.sin(a), r: 11,
      class: 'ring-led', fill: '#241912'
    }, svg));
  }
  function drawRing() {
    var k = 0.3 + 0.7 * ringBrightness;
    ringLeds.forEach(function (led, i) {
      var c = ringPixels[i];
      if (!c) { led.setAttribute('fill', '#241912'); led.style.filter = ''; return; }
      var r = parseInt(c.slice(1, 3), 16), g = parseInt(c.slice(3, 5), 16), b = parseInt(c.slice(5, 7), 16);
      led.setAttribute('fill', 'rgb(' + Math.round(r * k) + ',' + Math.round(g * k) + ',' + Math.round(b * k) + ')');
      led.style.filter = 'drop-shadow(0 0 ' + (3 + 6 * ringBrightness) + 'px ' + c + ')';
    });
  }
  drawRing();

  var platter = el('g', {}, svg);
  el('circle', { cx: RING.cx, cy: RING.cy, r: RING.bodyR, class: 'platter-body' }, platter);
  [100, 80, 60].forEach(function (r) { el('circle', { cx: RING.cx, cy: RING.cy, r: r, class: 'platter-groove' }, platter); });
  var platterRot = el('g', {}, platter);
  el('line', { x1: RING.cx, y1: RING.cy - 100, x2: RING.cx, y2: RING.cy - 58, class: 'platter-mark' }, platterRot);
  el('circle', { cx: RING.cx, cy: RING.cy, r: 14, fill: '#b8923f', stroke: '#5c4719', 'stroke-width': 2 }, platter);
  text('Platter', RING.cx, RING.cy + 90, 'sublabel', svg);
  var platterAngle = 0;

  var platterDrag = null;
  function pointerAngle(ev) {
    var p = svgPoint(ev);
    return Math.atan2(p.y - RING.cy, p.x - RING.cx) * 180 / Math.PI;
  }
  function turnPlatter(deg) {
    platterAngle += deg;
    platterRot.setAttribute('transform', 'rotate(' + platterAngle + ' ' + RING.cx + ' ' + RING.cy + ')');
  }
  platter.addEventListener('pointerdown', function (ev) {
    platter.setPointerCapture(ev.pointerId);
    platterDrag = { id: ev.pointerId, last: pointerAngle(ev), acc: 0 };
    platter.style.cursor = 'grabbing';
  });
  platter.addEventListener('pointermove', function (ev) {
    if (!platterDrag || ev.pointerId !== platterDrag.id) return;
    var a = pointerAngle(ev);
    var d = a - platterDrag.last;
    if (d > 180) d -= 360;
    if (d < -180) d += 360;
    platterDrag.last = a;
    turnPlatter(d);
    platterDrag.acc += d;
    var step = 360 / DETENTS_PER_TURN;
    var n = Math.trunc(platterDrag.acc / step);
    if (n) { platterDrag.acc -= n * step; client.platter(n); }
  });
  function endPlatter(ev) { if (platterDrag && ev.pointerId === platterDrag.id) { platterDrag = null; platter.style.cursor = ''; } }
  platter.addEventListener('pointerup', endPlatter);
  platter.addEventListener('pointercancel', endPlatter);
  platter.addEventListener('wheel', function (ev) {
    ev.preventDefault();
    var n = ev.deltaY > 0 ? 1 : -1; // scrolling down turns clockwise
    turnPlatter(n * 360 / DETENTS_PER_TURN);
    client.platter(n);
  }, { passive: false });

  // ---- keys -------------------------------------------------------------------------------
  var keyEls = {}; // id -> { g, down }
  function addKey(spec, shape, parent) {
    var g = el('g', { class: 'key', 'data-mode': spec.defaultMode || 'off', tabindex: 0, role: 'button', 'aria-label': spec.label }, parent || svg);
    g.style.setProperty('--glow', spec.glow || spec.color);
    var cap;
    if (shape.round) {
      el('circle', { cx: shape.x, cy: shape.y, r: shape.r + 6, class: 'glow-ring' }, g);
      cap = el('circle', { cx: shape.x, cy: shape.y, r: shape.r, class: 'cap', fill: spec.color }, g);
    } else {
      el('rect', { x: shape.x - shape.w / 2 - 5, y: shape.y - shape.w / 2 - 5, width: shape.w + 10, height: shape.w + 10, rx: 10, class: 'glow-ring' }, g);
      cap = el('rect', { x: shape.x - shape.w / 2, y: shape.y - shape.w / 2, width: shape.w, height: shape.w, rx: 8, class: 'cap', fill: spec.color }, g);
    }
    keyEls[spec.id] = { g: g, cap: cap, spec: spec };
    g.addEventListener('pointerdown', function (ev) {
      ev.preventDefault();
      g.setPointerCapture(ev.pointerId);
      pressKey(spec.id, true);
    });
    var up = function () { pressKey(spec.id, false); };
    g.addEventListener('pointerup', up);
    g.addEventListener('pointercancel', up);
    g.addEventListener('lostpointercapture', up);
    return g;
  }
  function pressKey(id, down) {
    var k = keyEls[id];
    if (!k) return;
    k.g.classList.toggle('down', down);
    client.key(id, down ? 'down' : 'up');
  }

  ROUND_KEYS.forEach(function (spec, i) {
    var x = 110 + i * 100;
    spec.defaultMode = spec.id === 'capture' ? 'on' : 'off';
    addKey(spec, { round: true, x: x, y: 505, r: 28 });
    text(spec.label, x, 568, 'sublabel', svg);
  });

  // ---- knobs ------------------------------------------------------------------------------
  var knobX = [635, 770, 905, 1040];
  KNOBS.forEach(function (k, i) {
    var x = knobX[i], y = 112;
    text(k.label, x, 50, 'label', svg);
    var g = el('g', {}, svg);
    el('circle', { cx: x, cy: y, r: KNOB_R + 7, fill: '#b8923f', opacity: 0.35 }, g);
    el('circle', { cx: x, cy: y, r: KNOB_R, class: 'knob-body' }, g);
    var rot = el('g', {}, g);
    el('line', { x1: x, y1: y - KNOB_R + 6, x2: x, y2: y - 14, class: 'knob-mark' }, rot);
    var angle = 0, drag = null;
    function turn(n) {
      angle += n * 15;
      rot.setAttribute('transform', 'rotate(' + angle + ' ' + x + ' ' + y + ')');
      client.knob(k.id, n);
    }
    g.addEventListener('pointerdown', function (ev) {
      g.setPointerCapture(ev.pointerId);
      drag = { id: ev.pointerId, y: ev.clientY, acc: 0 };
    });
    g.addEventListener('pointermove', function (ev) {
      if (!drag || ev.pointerId !== drag.id) return;
      drag.acc += drag.y - ev.clientY; // up is clockwise
      drag.y = ev.clientY;
      var scale = svg.getBoundingClientRect().width / 1180; // keep the feel the same at any size
      var n = Math.trunc(drag.acc / (KNOB_PX_PER_DETENT * scale));
      if (n) { drag.acc -= n * KNOB_PX_PER_DETENT * scale; turn(n); }
    });
    var end = function (ev) { if (drag && ev.pointerId === drag.id) drag = null; };
    g.addEventListener('pointerup', end);
    g.addEventListener('pointercancel', end);
    g.addEventListener('wheel', function (ev) { ev.preventDefault(); turn(ev.deltaY < 0 ? 1 : -1); }, { passive: false });
  });

  // ---- mixer: track keys and faders --------------------------------------------------------
  var faderEls = {};
  TRACKS.forEach(function (t, i) {
    var x = 600 + i * 96;
    text(t.label, x, 215, 'label', svg);
    addKey({ id: 'track.' + t.id, label: t.label, color: t.color, fixed: true, defaultMode: 'on', hotkey: String(i + 1) }, { x: x, y: 268, w: 58 });
    el('rect', { x: x - 6, y: FADER.top, width: 12, height: FADER.bottom - FADER.top, rx: 6, class: 'slot' }, svg);
    var h = el('g', { cursor: 'ns-resize' }, svg);
    el('rect', { x: x - FADER.handleW / 2, y: 0, width: FADER.handleW, height: FADER.handleH, rx: 6, class: 'handle' }, h);
    el('line', { x1: x - 10, y1: FADER.handleH / 2, x2: x + 10, y2: FADER.handleH / 2, class: 'handle-line' }, h);
    el('rect', { x: x - 4, y: 4, width: 8, height: 4, fill: t.color }, h);
    faderEls[t.id] = h;
    function place(v) {
      var cy = FADER.top + (1 - v) * (FADER.bottom - FADER.top);
      h.setAttribute('transform', 'translate(0 ' + (cy - FADER.handleH / 2) + ')');
    }
    place(client.faders[t.id]);
    faderEls[t.id].place = place;
    var dragging = false;
    function move(ev) {
      var p = svgPoint(ev);
      var v = 1 - (p.y - FADER.top) / (FADER.bottom - FADER.top);
      v = Math.max(0, Math.min(1, v));
      place(v);
      client.fader(t.id, v);
    }
    h.addEventListener('pointerdown', function (ev) { dragging = true; h.setPointerCapture(ev.pointerId); move(ev); });
    h.addEventListener('pointermove', function (ev) { if (dragging) move(ev); });
    var stop = function () { dragging = false; };
    h.addEventListener('pointerup', stop);
    h.addEventListener('pointercancel', stop);
    // a click on the slot jumps the handle there
    var hit = el('rect', { x: x - 20, y: FADER.top - 10, width: 40, height: FADER.bottom - FADER.top + 20, fill: 'transparent' }, svg);
    svg.insertBefore(hit, h);
    hit.addEventListener('pointerdown', function (ev) { dragging = true; h.setPointerCapture(ev.pointerId); move(ev); });
  });

  // ---- keyboard ---------------------------------------------------------------------------
  var hotkeys = {};
  ROUND_KEYS.forEach(function (s) { hotkeys[s.hotkey] = s.id; });
  TRACKS.forEach(function (t, i) { hotkeys[String(i + 1)] = 'track.' + t.id; });
  window.addEventListener('keydown', function (ev) {
    if (ev.repeat || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (/^(INPUT|TEXTAREA)$/.test((ev.target.tagName || ''))) return;
    var id = hotkeys[ev.key.toLowerCase()];
    if (id) { ev.preventDefault(); pressKey(id, true); }
  });
  window.addEventListener('keyup', function (ev) {
    var id = hotkeys[ev.key.toLowerCase()];
    if (id) pressKey(id, false);
  });

  // ---- lights from the app ----------------------------------------------------------------
  function setKeyLight(id, mode, color) {
    var k = keyEls[id];
    if (!k) return;
    k.g.setAttribute('data-mode', mode);
    if (color && !k.spec.fixed) {
      k.g.style.setProperty('--glow', color);
    }
  }

  // ---- log and connection UI --------------------------------------------------------------
  var logEl = document.getElementById('log');
  var showIn = document.getElementById('show-in');
  var lines = [];
  var screenSel = document.getElementById('screen');  // a label for the log only; never sent
  function logLine(entry) {
    if (entry.dir === 'in' && !showIn.checked) return;
    var m = entry.msg;
    var body = m.type + (m.payload !== undefined ? ' ' + JSON.stringify(m.payload) : '');
    var tag = entry.dir === 'in' ? '← ' : entry.sent ? '→ ' : '· ';
    var cls = entry.dir === 'in' ? 'in' : entry.sent ? 'out-sent' : 'out-dry';
    var d = document.createElement('div');
    d.className = cls;
    d.textContent = '[' + screenSel.value + '] ' + tag + '#' + m.seq + ' t=' + m.t + ' ' + body;
    var atEnd = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 4;
    logEl.appendChild(d);
    lines.push(d);
    if (lines.length > 300) logEl.removeChild(lines.shift());
    if (atEnd) logEl.scrollTop = logEl.scrollHeight;
    if (window.console && console.debug) console.debug(entry.sent ? 'panel send' : 'panel (not sent)', m);
  }
  document.getElementById('clear-log').addEventListener('click', function () {
    logEl.textContent = ''; lines = [];
  });

  var linkBadge = document.getElementById('link-badge');
  var appBadge = document.getElementById('app-badge');
  function showStatus(s) {
    var text = { offline: 'Offline (log only)', connecting: 'Connecting…', connected: 'Connected to server' }[s.link];
    linkBadge.textContent = text;
    linkBadge.dataset.state = s.link === 'connected' ? 'ok' : s.link === 'connecting' ? 'wait' : '';
    appBadge.textContent = s.app === null ? 'iPad unknown' : s.app ? 'iPad online' : 'iPad not connected';
    appBadge.dataset.state = s.app ? 'ok' : '';
  }

  var urlInput = document.getElementById('url');
  var STORE = 'fretcase.simulator.url';

  function connectFromInput() {
    var url = urlInput.value.trim();
    try { if (url) localStorage.setItem(STORE, url); else localStorage.removeItem(STORE); } catch (e) { /* private mode */ }
    client.start(url || null);
  }
  document.getElementById('link-form').addEventListener('submit', function (ev) { ev.preventDefault(); connectFromInput(); });
  document.getElementById('disconnect').addEventListener('click', function () { client.start(null); });

  // Start: ?ws=wss://host:8443/ws/panel connects at once; otherwise the last URL used is filled in
  // but not connected, and the panel runs offline (messages are logged, not sent).
  var params = new URLSearchParams(location.search);
  var saved = '';
  try { saved = localStorage.getItem(STORE) || ''; } catch (e) { /* ignore */ }
  var fromQuery = params.get('ws');
  urlInput.value = fromQuery || saved || '';
  client.start(fromQuery || null);

  window.fretcaseSimulator = { client: client };
})();
