import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PanelClient } from './client'
import { computeKeyLights, computeRing } from './lights'
import type { Song } from '../types'
import example from '../generated/example-song.json'

class FakeWS {
  static all: FakeWS[] = []
  readyState = 0
  sent: Record<string, unknown>[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(public url: string) { FakeWS.all.push(this) }
  open() { this.readyState = 1; this.onopen?.() }
  send(s: string) { this.sent.push(JSON.parse(s)) }
  close() { this.readyState = 3; this.onclose?.() }
  receive(m: unknown) { this.onmessage?.({ data: JSON.stringify(m) }) }
}

beforeEach(() => { vi.useFakeTimers(); FakeWS.all = []; vi.stubGlobal('performance', { now: () => Date.now() }) })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

function client() {
  const msgs: unknown[] = []
  const statuses: unknown[] = []
  const c = new PanelClient('ws://x/ws/panel', (m) => msgs.push(m), (s) => statuses.push(s), FakeWS as unknown as typeof WebSocket)
  c.start()
  return { c, msgs, statuses, ws: () => FakeWS.all.at(-1)! }
}

describe('PanelClient', () => {
  it('says hello as the app and numbers its messages', () => {
    const { c, ws } = client()
    ws().open()
    c.setRing(Array(16).fill('#112233'))
    c.setKeyLight('capture', 'blink', '#d64533')
    expect(ws().sent.map((m) => [m.type, m.seq, m.v])).toEqual([['hello', 0, 1], ['ring.set', 1, 1], ['key.light', 2, 1]])
    expect((ws().sent[0].payload as { role: string }).role).toBe('app')
  })

  it('sends hello before anything the connected status triggers', () => {
    const msgs: unknown[] = []
    let c: PanelClient
    // Like the controller: on connect it syncs the lights straight away.
    c = new PanelClient('ws://x/ws/panel', (m) => msgs.push(m), (s) => { if (s.connected) c.setRing(Array(16).fill('#112233')) }, FakeWS as unknown as typeof WebSocket)
    c.start()
    const ws = FakeWS.all.at(-1)!
    ws.open()
    expect(ws.sent.map((m) => m.type)).toEqual(['hello', 'ring.set'])
  })

  it('forwards panel messages, answers ping, tracks peer.status, ignores garbage', () => {
    const { ws, msgs, statuses } = client()
    ws().open()
    ws().receive({ v: 1, type: 'platter.turn', seq: 0, t: 5, payload: { delta: 2 } })
    ws().receive({ v: 1, type: 'ping', seq: 1, t: 6 })
    ws().receive({ v: 1, type: 'peer.status', seq: 2, t: 7, payload: { panel: true, app: true } })
    ws().onmessage?.({ data: 'not json' })
    ws().receive({ v: 2, type: 'platter.turn', seq: 3, t: 8, payload: { delta: 1 } })
    expect(msgs).toHaveLength(2)
    expect(ws().sent.some((m) => m.type === 'pong')).toBe(true)
    expect(statuses.at(-1)).toEqual({ connected: true, panel: true })
  })

  it('refuses to send panel-only messages', () => {
    const { c, ws } = client()
    ws().open()
    expect(() => c.send({ type: 'platter.turn', payload: { delta: 1 } })).toThrow()
  })

  it('pings every 2 s and reconnects when nothing is heard for 5 s', () => {
    const { ws } = client()
    const first = ws()
    first.open()
    vi.advanceTimersByTime(2000)
    expect(first.sent.filter((m) => m.type === 'ping')).toHaveLength(1)
    vi.advanceTimersByTime(4100)
    expect(first.readyState).toBe(3)
    vi.advanceTimersByTime(600)
    expect(FakeWS.all.length).toBe(2)
  })

  it('reconnects after a close, with growing delay', () => {
    const { ws } = client()
    ws().close()
    vi.advanceTimersByTime(500)
    expect(FakeWS.all.length).toBe(2)
    ws().close()
    vi.advanceTimersByTime(900)
    expect(FakeWS.all.length).toBe(2)
    vi.advanceTimersByTime(200)
    expect(FakeWS.all.length).toBe(3)
  })
})

const song = () => JSON.parse(JSON.stringify(example)) as Song

describe('lights', () => {
  it('ring has 16 pixels, accent at the position, dimmed locked sections', () => {
    const s = song()
    s.locks = [{ section: 's-verse' }]
    const ring = computeRing(s, 0)
    expect(ring).toHaveLength(16)
    expect(ring[0]).toBe('#e08a12')
    expect(ring[5]).toBe('#3a2a1c') // bar 5 is in the locked verse
    expect(ring[10]).not.toBe('#3a2a1c')
    expect(computeRing(s, 8.5)[8]).toBe('#e08a12')
    expect(computeRing(s, 16)[15]).toBe('#e08a12')
    expect(computeRing(null, 0).every((p) => p === null)).toBe(true)
  })

  it('a track-only lock does not dim the ring', () => {
    const s = song()
    s.locks = [{ track: 'melody' }]
    expect(computeRing(s, 0).filter((p) => p === '#3a2a1c')).toHaveLength(0)
  })

  it('key lights: muted off, selected full colour, others dimmer, capture blinks while recording', () => {
    const s = song()
    s.tracks.drums.muted = true
    const l = computeKeyLights({ song: s, selected: 'guitar', recording: true, busy: false, playing: false })
    const by = Object.fromEntries(l.map((k) => [k.id, k]))
    expect(by['track.drums'].mode).toBe('off')
    expect(by['track.guitar'].color).toBe('#4FB3A6')
    expect(by['track.bass'].color).not.toBe('#6C93D6')
    expect(by.capture.mode).toBe('blink')
    expect(by.play.mode).toBe('off')
  })
})
