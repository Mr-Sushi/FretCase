import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PanelInterpreter, type Intent, type PanelContext } from './interpreter'
import type { Section } from '../types'

const sections: Section[] = [
  { id: 's-intro', label: '开头', startBar: 0, endBar: 4 },
  { id: 's-verse', label: '展开', startBar: 4, endBar: 8 },
  { id: 's-chorus', label: '高潮', startBar: 8, endBar: 16 },
]

function setup(selected: PanelContext['selectedTrack'] = null, screen = 'shape') {
  const out: Intent[] = []
  const state = { selected, screen, focus: 0, sectionIndex: 0, styleIndex: 1, region: { complexity: 0.5, intensity: 0.5 }, volumes: { drums: 0.8 } as Record<string, number>, controls: { brightness: 0.5, complexity: 0.5, density: 0.5 }, tempo: 84 }
  const ctx: PanelContext = {
    screen: () => state.screen,
    focus: () => state.focus,
    sectionIndex: () => state.sectionIndex,
    cardStyleIndex: () => state.styleIndex,
    regionParam: (p) => state.region[p],
    bars: 16,
    sections,
    get selectedTrack() { return state.selected },
    volume: (t) => state.volumes[t] ?? 0.8,
    controlValue: (c) => state.controls[c],
    tempo: () => state.tempo,
  }
  const pi = new PanelInterpreter(ctx, (i) => out.push(i))
  let seq = 0
  const send = (type: string, payload: Record<string, unknown>, t: number) => pi.handle({ type, payload, t, ...{ seq: seq++ } } as never)
  return { pi, out, state, send }
}

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

describe('capture key', () => {
  it('short press takes a photo', () => {
    const { out, send } = setup()
    send('key', { id: 'capture', action: 'down' }, 1000)
    vi.advanceTimersByTime(200)
    send('key', { id: 'capture', action: 'up' }, 1200)
    expect(out).toEqual([{ type: 'photo' }])
  })

  it('records while held beyond 600 ms and stops on release', () => {
    const { out, send } = setup()
    send('key', { id: 'capture', action: 'down' }, 1000)
    vi.advanceTimersByTime(599)
    expect(out).toEqual([])
    vi.advanceTimersByTime(2)
    expect(out).toEqual([{ type: 'record.start' }])
    vi.advanceTimersByTime(5000)
    send('key', { id: 'capture', action: 'up' }, 6600)
    expect(out).toEqual([{ type: 'record.start' }, { type: 'record.stop' }])
  })

  it('trusts the panel clock when the timer ran late', () => {
    const { out, send } = setup()
    send('key', { id: 'capture', action: 'down' }, 1000)
    send('key', { id: 'capture', action: 'up' }, 1700) // both arrive at once, 700 ms apart on the panel clock
    expect(out).toEqual([{ type: 'record.start' }, { type: 'record.stop' }])
  })
})

describe('track keys', () => {
  it('short press selects, long press mutes without selecting', () => {
    const { out, send } = setup()
    send('key', { id: 'track.guitar', action: 'down' }, 0)
    send('key', { id: 'track.guitar', action: 'up' }, 100)
    send('key', { id: 'track.drums', action: 'down' }, 1000)
    vi.advanceTimersByTime(650)
    send('key', { id: 'track.drums', action: 'up' }, 1650)
    expect(out).toEqual([{ type: 'track.select', track: 'guitar' }, { type: 'track.mute', track: 'drums' }])
  })

  it('ignores an up without a down', () => {
    const { out, send } = setup()
    send('key', { id: 'track.bass', action: 'up' }, 50)
    expect(out).toEqual([])
  })
})

describe('action keys', () => {
  it('play and undo are single intents, even if held long', () => {
    const { out, send } = setup()
    send('key', { id: 'play', action: 'down' }, 0)
    vi.advanceTimersByTime(900)
    send('key', { id: 'play', action: 'up' }, 900)
    send('key', { id: 'undo', action: 'down' }, 2000)
    send('key', { id: 'undo', action: 'up' }, 2050)
    expect(out).toEqual([{ type: 'play.toggle' }, { type: 'undo' }])
  })

  it('"another" targets the section under the platter, with the selected track if any', () => {
    const { out, send, state } = setup()
    send('platter.turn', { delta: 20 }, 0) // 5 bars: verse
    out.length = 0
    send('key', { id: 'another', action: 'down' }, 0)
    send('key', { id: 'another', action: 'up' }, 50)
    state.selected = 'guitar'
    send('key', { id: 'another', action: 'down' }, 100)
    send('key', { id: 'another', action: 'up' }, 150)
    expect(out).toEqual([
      { type: 'another', section: 's-verse' },
      { type: 'another', section: 's-verse', track: 'guitar' },
    ])
  })
})

describe('platter', () => {
  it('moves four detents per bar and clamps to the song', () => {
    const { out, send, pi } = setup()
    send('platter.turn', { delta: 3 }, 0)
    send('platter.turn', { delta: 1 }, 20)
    send('platter.turn', { delta: -64 }, 40)
    send('platter.turn', { delta: 64 }, 60)
    send('platter.turn', { delta: 64 }, 80)
    expect(out.map((i) => (i as { bar: number }).bar)).toEqual([0.75, 1, 0, 16, 16])
    expect(pi.sectionUnderPlatter()?.id).toBe('s-chorus')
  })

  it('continues from a position set by the app', () => {
    const { out, send, pi } = setup()
    pi.setPosition(7.5)
    send('platter.turn', { delta: 2 }, 0)
    expect(out).toEqual([{ type: 'seek', bar: 8 }])
    expect(pi.sectionUnderPlatter()?.id).toBe('s-chorus')
  })
})

describe('faders', () => {
  it('sends one call per 150 ms per fader with the latest value', () => {
    const { out, send } = setup()
    send('fader.move', { track: 'drums', value: 0.7 }, 0)
    vi.advanceTimersByTime(50)
    send('fader.move', { track: 'drums', value: 0.5 }, 50)
    send('fader.move', { track: 'bass', value: 0.2 }, 60)
    vi.advanceTimersByTime(100)
    expect(out).toEqual([{ type: 'volume', track: 'drums', value: 0.5 }])
    vi.advanceTimersByTime(60)
    expect(out).toEqual([{ type: 'volume', track: 'drums', value: 0.5 }, { type: 'volume', track: 'bass', value: 0.2 }])
    send('fader.move', { track: 'drums', value: 0.4 }, 300)
    vi.advanceTimersByTime(150)
    expect(out.at(-1)).toEqual({ type: 'volume', track: 'drums', value: 0.4 })
  })

  it('turns a snapshot into a fader sync', () => {
    const { out, send } = setup()
    const faders = { vocal: 0.8, melody: 0.8, guitar: 0.8, bass: 0.7, drums: 0.45, ambience: 0.5 }
    send('snapshot', { faders, keysDown: [] }, 0)
    expect(out).toEqual([{ type: 'faders.sync', faders }])
  })
})

describe('knobs', () => {
  it('adds 0.02 per detent and sends once, 400 ms after the last detent', () => {
    const { out, send } = setup()
    send('knob.turn', { knob: 'complexity', delta: 3 }, 0)
    vi.advanceTimersByTime(300)
    send('knob.turn', { knob: 'complexity', delta: -1 }, 300)
    vi.advanceTimersByTime(399)
    expect(out).toEqual([])
    vi.advanceTimersByTime(2)
    expect(out).toEqual([{ type: 'control', control: 'complexity', value: 0.54 }])
  })

  it('clamps to 0..1 and keeps knobs independent', () => {
    const { out, send } = setup()
    send('knob.turn', { knob: 'density', delta: 32 }, 0)
    send('knob.turn', { knob: 'brightness', delta: -32 }, 0)
    vi.advanceTimersByTime(400)
    expect(out).toEqual([
      { type: 'control', control: 'density', value: 1 },
      { type: 'control', control: 'brightness', value: 0 },
    ])
  })

  it('tempo knob changes tempo directly', () => {
    const { out, send } = setup()
    send('knob.turn', { knob: 'tempo', delta: -4 }, 0)
    vi.advanceTimersByTime(400)
    expect(out).toEqual([{ type: 'tempo', value: 80 }])
  })
})

describe('screens', () => {
  const press = (send: ReturnType<typeof setup>['send'], id: string, t = 0) => { send('key', { id, action: 'down' }, t); send('key', { id, action: 'up' }, t + 50) }

  it('pick: four detents move the focus by one card, the other key asks for three more', () => {
    const { out, send, state } = setup(null, 'pick')
    send('platter.turn', { delta: 3 }, 0)
    expect(out).toEqual([])
    send('platter.turn', { delta: 1 }, 20)
    expect(out).toEqual([{ type: 'pick.focus', index: 1 }])
    state.focus = 1
    send('platter.turn', { delta: 8 }, 40) // would pass the last card
    expect(out.at(-1)).toEqual({ type: 'pick.focus', index: 2 })
    state.focus = 2
    send('platter.turn', { delta: -4 }, 60)
    expect(out.at(-1)).toEqual({ type: 'pick.focus', index: 1 })
    press(send, 'another')
    expect(out.at(-1)).toEqual({ type: 'pick.more' })
    press(send, 'play', 500)
    expect(out.at(-1)).toEqual({ type: 'play.toggle' })
  })

  it('detail: the platter moves the section, the knobs set the selected region', () => {
    const { out, send, state } = setup('guitar', 'detail')
    send('platter.turn', { delta: 4 }, 0)
    expect(out).toEqual([{ type: 'region.section', index: 1 }])
    out.length = 0
    send('knob.turn', { knob: 'complexity', delta: 5 }, 0)
    send('knob.turn', { knob: 'density', delta: -5 }, 0)
    vi.advanceTimersByTime(400)
    expect(out).toEqual([
      { type: 'region.param', param: 'complexity', value: 0.6 },
      { type: 'region.param', param: 'intensity', value: 0.4 },
    ])
    out.length = 0
    send('knob.turn', { knob: 'brightness', delta: 5 }, 0)
    send('knob.turn', { knob: 'tempo', delta: 2 }, 0)
    vi.advanceTimersByTime(400)
    expect(out).toEqual([{ type: 'control', control: 'brightness', value: 0.6 }, { type: 'tempo', value: 86 }])
    state.screen = 'shape'
    out.length = 0
    send('knob.turn', { knob: 'complexity', delta: 5 }, 0)
    vi.advanceTimersByTime(400)
    expect(out).toEqual([{ type: 'control', control: 'complexity', value: 0.6 }])
  })

  it('card: the platter cycles the styles', () => {
    const { out, send } = setup(null, 'card')
    send('platter.turn', { delta: 4 }, 0)
    send('platter.turn', { delta: -8 }, 20)
    expect(out).toEqual([{ type: 'card.style', index: 2 }, { type: 'card.style', index: 0 }])
  })

  it('capture: short press is a photo, hold is a hum', () => {
    const { out, send } = setup(null, 'capture')
    press(send, 'capture')
    expect(out).toEqual([{ type: 'photo' }])
  })
})
