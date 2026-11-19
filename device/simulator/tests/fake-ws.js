'use strict';
// A minimal stand-in for the browser WebSocket.
class FakeWebSocket {
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }
  open() { this.readyState = 1; if (this.onopen) this.onopen({}); }
  receive(obj) { if (this.onmessage) this.onmessage({ data: typeof obj === 'string' ? obj : JSON.stringify(obj) }); }
  send(data) { this.sent.push(JSON.parse(data)); }
  close() { this.readyState = 3; }
  drop() { this.readyState = 3; if (this.onclose) this.onclose({}); }
  static reset() { FakeWebSocket.instances = []; }
}
FakeWebSocket.instances = [];
module.exports = FakeWebSocket;
