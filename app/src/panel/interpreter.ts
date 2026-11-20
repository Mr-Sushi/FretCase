import type { KeyId, KnobId, TrackId } from '../types'
import { TRACK_IDS, clamp, sectionAtBar } from '../lib/song'
import type { Section } from '../types'

/** What the app should do. The interpreter only decides; the controller acts. */
export type Intent =
  | { type: 'record.start' }
  | { type: 'record.stop' }
  | { type: 'photo' }
  | { type: 'play.toggle' }
  | { type: 'undo' }
  | { type: 'another'; section: string; track?: TrackId }
  | { type: 'track.select'; track: TrackId }
  | { type: 'track.mute'; track: TrackId }
  | { type: 'seek'; bar: number }
  /** A platter turn while the song plays: played like a record; `bar` is where a plain seek would go. */
  | { type: 'jog'; delta: number; bar: number }
  | { type: 'volume'; track: TrackId; value: number }
  | { type: 'control'; control: 'brightness' | 'complexity' | 'density'; value: number }
  | { type: 'tempo'; value: number }
  | { type: 'faders.sync'; faders: Record<TrackId, number> }
  | { type: 'pick.focus'; index: number }
  | { type: 'pick.more' }
  | { type: 'region.section'; index: number }
  | { type: 'region.param'; param: 'complexity' | 'intensity'; value: number }
  | { type: 'card.style'; index: number }
  | { type: 'pick.choose'; index: number }
  | { type: 'card.print' }
  | { type: 'card.printHint' }

/** The part of the app state the interpretation needs. Read at the moment of use. */
export interface PanelContext {
  /** Which screen is showing: the same meaning of the panel's controls changes with it. */
  screen(): string
  focus(): number
  sectionIndex(): number
  cardStyleIndex(): number
  /** Complexity or intensity of the selected region on the track screen, or null when none is selected. */
  regionParam(param: 'complexity' | 'intensity'): number | null
  bars: number
  sections: Section[]
  selectedTrack: TrackId | null
  volume(track: TrackId): number
  controlValue(control: 'brightness' | 'complexity' | 'density'): number
  tempo(): number
  /** Whether the song is playing: then the platter plays it like a record instead of moving the position. */
  playing(): boolean
}

export interface InterpreterOptions {
  longPressMs: number
  detentsPerBar: number
  faderDebounceMs: number
  knobDebounceMs: number
  /** One feel-knob detent changes the value by this much (docs/api.md: 0.02). */
  knobStep: number
  /** Platter detents per step where the platter chooses between a few things (cards, sections, card styles). */
  detentsPerStep: number
  /** Tempo knob: quarter notes per minute per detent. Not specified by docs/api.md. */
  tempoStep: number
  /** On the card screen the capture key prints only when held this long: a print uses film and cannot be undone. */
  printHoldMs: number
}

export const DEFAULT_OPTIONS: InterpreterOptions = {
  longPressMs: 600,
  detentsPerBar: 4,
  faderDebounceMs: 150,
  knobDebounceMs: 400,
  knobStep: 0.02,
  tempoStep: 1,
  detentsPerStep: 4,
  printHoldMs: 1000,
}

interface Msg { type: string; t?: number; payload?: Record<string, unknown> }

/**
 * Turns raw panel messages (docs/api.md, "Panel WebSocket") into intents:
 * long press at 600 ms (record while held / mute), short press (photo / select), platter detents
 * moving the play position (4 per bar), faders debounced to one call per 150 ms per fader,
 * feel knobs debounced to one call 400 ms after the last detent.
 */
export class PanelInterpreter {
  private stepAcc = 0
  private lastScreen = ''
  private position = 0 // in bars, fractional; one detent moves 1/detentsPerBar
  private downAt = new Map<KeyId, { t: number; timer: ReturnType<typeof setTimeout>; long: boolean; print?: boolean }>()
  private faderTimers = new Map<TrackId, { timer: ReturnType<typeof setTimeout>; value: number }>()
  private knobTimers = new Map<KnobId, { timer: ReturnType<typeof setTimeout>; value: number }>()
  private opts: InterpreterOptions

  constructor(private ctx: PanelContext, private emit: (i: Intent) => void, opts: Partial<InterpreterOptions> = {}) {
    this.opts = { ...DEFAULT_OPTIONS, ...opts }
  }

  /** The app moves the play position (playback, screen taps); the platter continues from there. */
  setPosition(bar: number) { this.position = clamp(bar, 0, this.ctx.bars) }
  getPosition() { return this.position }

  dispose() {
    for (const d of this.downAt.values()) clearTimeout(d.timer)
    for (const f of this.faderTimers.values()) clearTimeout(f.timer)
    for (const k of this.knobTimers.values()) clearTimeout(k.timer)
    this.downAt.clear(); this.faderTimers.clear(); this.knobTimers.clear()
  }

  handle(msg: Msg) {
    const p = msg.payload ?? {}
    switch (msg.type) {
      case 'snapshot': return this.snapshot(p)
      case 'platter.turn': return this.platter(p.delta as number)
      case 'knob.turn': return this.knob(p.knob as KnobId, p.delta as number)
      case 'fader.move': return this.fader(p.track as TrackId, p.value as number)
      case 'key': return this.key(p.id as KeyId, p.action as 'down' | 'up', msg.t ?? 0)
    }
  }

  /** Section the platter is on: the target of "another". */
  sectionUnderPlatter(): Section | undefined {
    // The position can sit exactly at the end of the song; the last bar belongs to the last section.
    return sectionAtBar(this.ctx.sections, Math.min(this.position, this.ctx.bars - 1e-6))
  }

  // ---- platter ----------------------------------------------------------------------------

  private platter(delta: number) {
    if (!Number.isInteger(delta) || delta === 0) return
    const screen = this.ctx.screen()
    if (screen !== this.lastScreen) { this.lastScreen = screen; this.stepAcc = 0 }
    const stepper = screen === 'pick' ? { count: 3, cur: this.ctx.focus(), type: 'pick.focus' as const }
      : screen === 'detail' ? { count: this.ctx.sections.length, cur: this.ctx.sectionIndex(), type: 'region.section' as const }
      : screen === 'card' ? { count: 5, cur: this.ctx.cardStyleIndex(), type: 'card.style' as const }
      : null
    if (stepper) {
      // Detents add up; every `detentsPerStep` of them moves the choice by one.
      const total = this.stepAcc + delta
      const steps = Math.trunc(total / this.opts.detentsPerStep)
      this.stepAcc = total - steps * this.opts.detentsPerStep
      if (steps === 0) return
      const index = clamp(stepper.cur + steps, 0, stepper.count - 1)
      if (index !== stepper.cur) this.emit({ type: stepper.type, index })
      return
    }
    this.position = clamp(this.position + delta / this.opts.detentsPerBar, 0, this.ctx.bars)
    if (this.ctx.playing()) this.emit({ type: 'jog', delta, bar: this.position })
    else this.emit({ type: 'seek', bar: this.position })
  }

  // ---- knobs ------------------------------------------------------------------------------

  private knob(knob: KnobId, delta: number) {
    if (!Number.isInteger(delta) || delta === 0) return
    const pending = this.knobTimers.get(knob)
    // On the track screen the complexity and density knobs set the selected region's complexity and intensity.
    const param = this.ctx.screen() === 'detail' ? (knob === 'complexity' ? 'complexity' : knob === 'density' ? 'intensity' : null) : null
    const regionNow = param ? this.ctx.regionParam(param) : null
    const toRegion = param !== null && regionNow !== null
    const start = pending
      ? pending.value
      : knob === 'tempo' ? this.ctx.tempo() : toRegion ? regionNow : this.ctx.controlValue(knob)
    const value = knob === 'tempo'
      ? clamp(Math.round(start + delta * this.opts.tempoStep), 40, 220)
      : clamp(Math.round((start + delta * this.opts.knobStep) * 1000) / 1000, 0, 1)
    if (pending) clearTimeout(pending.timer)
    const timer = setTimeout(() => {
      this.knobTimers.delete(knob)
      if (knob === 'tempo') this.emit({ type: 'tempo', value })
      else if (toRegion) this.emit({ type: 'region.param', param: param!, value })
      else this.emit({ type: 'control', control: knob, value })
    }, this.opts.knobDebounceMs)
    this.knobTimers.set(knob, { timer, value })
  }

  /** Value a knob will have once its debounce fires, for showing it on screen at once. */
  pendingKnob(knob: KnobId): number | undefined { return this.knobTimers.get(knob)?.value }

  // ---- faders -----------------------------------------------------------------------------

  private fader(track: TrackId, value: number) {
    if (!TRACK_IDS.includes(track) || typeof value !== 'number') return
    const v = clamp(value, 0, 1)
    // Throttle: the first movement is sent after the debounce window, later ones replace its value.
    const pending = this.faderTimers.get(track)
    if (pending) { pending.value = v; return }
    const entry = { value: v, timer: setTimeout(() => {
      this.faderTimers.delete(track)
      this.emit({ type: 'volume', track, value: entry.value })
    }, this.opts.faderDebounceMs) }
    this.faderTimers.set(track, entry)
  }

  /** Fader value to show at once, before the debounced call goes out. */
  pendingFader(track: TrackId): number | undefined { return this.faderTimers.get(track)?.value }

  private snapshot(p: Record<string, unknown>) {
    const f = p.faders as Record<TrackId, number> | undefined
    if (!f) return
    this.emit({ type: 'faders.sync', faders: { ...f } })
    // A key already held when the app connects is ignored: its press started before we could time it.
  }

  // ---- keys -------------------------------------------------------------------------------

  private key(id: KeyId, action: 'down' | 'up', t: number) {
    if (action === 'down') {
      const old = this.downAt.get(id)
      if (old) clearTimeout(old.timer)
      if (id === 'capture' && this.ctx.screen() === 'card') {
        // The capture key confirms the print, and only when held: a print uses film and cannot be undone.
        const rec: { t: number; long: boolean; print: boolean; timer: ReturnType<typeof setTimeout> } = { t, long: false, print: true, timer: setTimeout(() => this.printHold(rec), this.opts.printHoldMs) }
        this.downAt.set(id, rec)
        return
      }
      const rec = { t, long: false, timer: setTimeout(() => this.longPress(id, rec), this.opts.longPressMs) }
      this.downAt.set(id, rec)
      return
    }
    const rec = this.downAt.get(id)
    if (!rec) return // an up without a down (e.g. held before connecting)
    clearTimeout(rec.timer)
    this.downAt.delete(id)
    if (rec.print) {
      if (!rec.long && t - rec.t >= this.opts.printHoldMs) this.printHold(rec)
      if (!rec.long) this.emit({ type: 'card.printHint' })
      return
    }
    // The panel's clock decides if the timer was late: a press the panel measured as long is long.
    if (!rec.long && t - rec.t >= this.opts.longPressMs) this.longPress(id, rec)
    if (rec.long) {
      if (id === 'capture') this.emit({ type: 'record.stop' })
      return
    }
    this.shortPress(id)
  }

  private printHold(rec: { long: boolean }) {
    if (rec.long) return
    rec.long = true
    this.emit({ type: 'card.print' })
  }

  private longPress(id: KeyId, rec: { long: boolean }) {
    if (rec.long) return
    // Only the capture key and the track keys have a long-press meaning; holding any other key is a short press.
    if (id !== 'capture' && !id.startsWith('track.')) return
    rec.long = true
    if (id === 'capture') this.emit({ type: 'record.start' })
    else if (id.startsWith('track.')) this.emit({ type: 'track.mute', track: id.slice(6) as TrackId })
  }

  private shortPress(id: KeyId) {
    switch (id) {
      case 'capture':
        // Where nothing is captured, the capture key confirms: on the pick screen it chooses the song in focus.
        if (this.ctx.screen() === 'pick') { this.emit({ type: 'pick.choose', index: this.ctx.focus() }); return }
        this.emit({ type: 'photo' }); return
      case 'play': this.emit({ type: 'play.toggle' }); return
      case 'undo': this.emit({ type: 'undo' }); return
      case 'another': {
        if (this.ctx.screen() === 'pick') { this.emit({ type: 'pick.more' }); return }
        // On the track screen the platter moves the selected region, so "another" acts on that section.
        const s = this.ctx.screen() === 'detail' ? this.ctx.sections[this.ctx.sectionIndex()] : this.sectionUnderPlatter()
        if (!s) return
        const track = this.ctx.selectedTrack ?? undefined
        this.emit(track ? { type: 'another', section: s.id, track } : { type: 'another', section: s.id })
        return
      }
      default:
        if (id.startsWith('track.')) this.emit({ type: 'track.select', track: id.slice(6) as TrackId })
    }
  }
}
