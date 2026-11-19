import type { PanelMessage } from '../types'

type Handler = (msg: { type: string; t?: number; payload?: Record<string, unknown> }) => void

export interface PanelStatus { connected: boolean; panel: boolean }

export function panelUrl(): string {
  const q = new URLSearchParams(location.search).get('panel')
  if (q) return q
  return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/panel`
}

const SENDABLE = new Set(['hello', 'ring.set', 'key.light', 'ping', 'pong'])

/**
 * App side of /ws/panel. Connects with role "app", pings every 2 s, treats 5 s without a pong
 * (or any message) as a dead link and reconnects with a short back-off.
 */
export class PanelClient {
  private ws: WebSocket | null = null
  private seq = 0
  private pingTimer: ReturnType<typeof setInterval> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private lastRx = 0
  private attempts = 0
  private closed = false
  private status: PanelStatus = { connected: false, panel: false }

  constructor(
    private url: string,
    private onMessage: Handler,
    private onStatus: (s: PanelStatus) => void,
    private WS: typeof WebSocket = WebSocket,
    private name = 'ipad',
  ) {}

  start() { this.closed = false; this.connect() }
  stop() {
    this.closed = true
    this.clearTimers()
    this.ws?.close()
    this.ws = null
    this.setStatus({ connected: false, panel: false })
  }
  get connected() { return this.status.connected }

  private setStatus(s: PanelStatus) {
    if (s.connected === this.status.connected && s.panel === this.status.panel) return
    this.status = s
    this.onStatus(s)
  }

  private clearTimers() {
    if (this.pingTimer) clearInterval(this.pingTimer)
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.pingTimer = this.reconnectTimer = null
  }

  private connect() {
    if (this.closed) return
    let ws: WebSocket
    try { ws = new this.WS(this.url) } catch { this.scheduleReconnect(); return }
    this.ws = ws
    this.seq = 0
    ws.onopen = () => {
      this.attempts = 0
      this.lastRx = Date.now()
      // hello must be the first frame: setStatus triggers the light sync.
      this.send({ type: 'hello', payload: { role: 'app', name: this.name } })
      this.setStatus({ connected: true, panel: this.status.panel })
      this.pingTimer = setInterval(() => {
        if (Date.now() - this.lastRx > 5000) { ws.close(); return }
        this.send({ type: 'ping' })
      }, 2000)
    }
    ws.onmessage = (ev) => {
      this.lastRx = Date.now()
      let msg: { v?: number; type?: string; t?: number; payload?: Record<string, unknown> }
      try { msg = JSON.parse(String(ev.data)) } catch { return }
      if (msg.v !== 1 || typeof msg.type !== 'string') return
      if (msg.type === 'ping') { this.send({ type: 'pong' }); return }
      if (msg.type === 'pong') return
      if (msg.type === 'peer.status') this.setStatus({ connected: true, panel: !!msg.payload?.panel })
      this.onMessage(msg as Parameters<Handler>[0])
    }
    ws.onclose = () => {
      this.clearTimers()
      this.ws = null
      this.setStatus({ connected: false, panel: false })
      this.scheduleReconnect()
    }
    ws.onerror = () => { /* onclose follows */ }
  }

  private scheduleReconnect() {
    if (this.closed || this.reconnectTimer) return
    const delay = Math.min(5000, 500 * 2 ** this.attempts++)
    this.reconnectTimer = setTimeout(() => { this.reconnectTimer = null; this.connect() }, delay)
  }

  /** Sends one message of a type the app may send (hello, ring.set, key.light, ping, pong). */
  send(m: { type: string; payload?: unknown }): boolean {
    if (!SENDABLE.has(m.type)) throw new Error(`app must not send ${m.type}`)
    if (!this.ws || this.ws.readyState !== 1) return false
    const msg = { v: 1, type: m.type, seq: this.seq++, t: Math.round(performance.now()), ...(m.payload !== undefined ? { payload: m.payload } : {}) } as PanelMessage
    this.ws.send(JSON.stringify(msg))
    return true
  }

  setRing(pixels: (string | null)[], brightness = 0.6) { return this.send({ type: 'ring.set', payload: { pixels, brightness } }) }
  setKeyLight(id: string, mode: 'off' | 'on' | 'blink' | 'pulse', color?: string) {
    return this.send({ type: 'key.light', payload: color ? { id, mode, color } : { id, mode } })
  }
}
